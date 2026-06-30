"""Existing Agent log analysis workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agent import report_renderer
from agent.context_builder import extract_list
from agent.evidence_builder import (
    build_log_analysis_evidence_trace,
    build_log_analysis_safety_evaluation,
)
from agent.llm.client import LLMUnavailable
from agent.llm.planner import LLMOutputParseError, analyze_log_with_llm
from agent.orchestration_common import (
    llm_result,
    make_agent_log_dir,
    now_iso,
    raw_from_exception,
)
from agent.report_writer import write_agent_artifacts
from agent.retrieval_context import build_log_rag_query, perform_retrieval
from agent.tool_validator import validate_llm_output_schema
from agent.tools import langchain_wrappers as tools
from agent.tools.log_analyzer import analyze_summary


def run_log_analysis_agent(args: argparse.Namespace) -> int:
    source_log_dir = Path(args.log_dir)
    source_summary_path = source_log_dir / "summary.json"
    if not source_summary_path.is_file():
        raise SystemExit(
            f"summary.json not found under log directory: {source_log_dir}"
        )

    source_summary = json.loads(
        source_summary_path.read_text(encoding="utf-8")
    )
    log_dir = make_agent_log_dir()

    print("LLM Agent Log Analysis")
    print(f"Source log dir: {source_log_dir}")
    print("\nCalling tool: log_analyzer")
    analyzer_result = tools.log_analyzer(str(source_log_dir))
    analyzer_result["tool"] = "log_analyzer"
    print(
        f"exitCode={analyzer_result['exitCode']} "
        f"status={analyzer_result['status']}"
    )

    analysis_path = source_log_dir / "analysis.md"
    analysis_text = (
        analysis_path.read_text(encoding="utf-8")
        if analysis_path.is_file()
        else ""
    )
    deterministic_analysis = analyze_summary(
        source_log_dir,
        source_summary,
    )
    retrieval = perform_retrieval(
        build_log_rag_query(source_summary, analysis_text),
        limit=3,
        purpose="log-analysis",
    )
    retrieved = retrieval["selectedContext"]
    planner_result = call_log_planner(
        source_summary,
        analysis_text,
        retrieved,
        deterministic_analysis,
    )

    errors = (
        []
        if analyzer_result["exitCode"] == 0
        else ["log_analyzer failed"]
    )
    warnings = list(source_summary.get("warnings") or [])
    if planner_result.get("fallbackUsed"):
        warnings.append(
            "Local LLM 분석을 생략하거나 사용할 수 없어 검증된 규칙 기반 분석 결과를 사용했습니다."
        )

    summary = {
        "mode": "log-analysis",
        "planner": "llm",
        "llmPlannerUsed": planner_result["llmPlannerUsed"],
        "localLLM": planner_result.get("localLLM") or {},
        "llmError": planner_result["error"],
        "sourceLogDir": str(source_log_dir),
        "sourceSummary": str(source_summary_path),
        "sourceAnalysis": str(analysis_path),
        "createdAt": now_iso(),
        "logAnalyzerResult": analyzer_result,
        "retrievedKnowledge": retrieved,
        "retrievalDetails": retrieval,
        "llmAnalysis": planner_result.get("llmOutput") or {},
        "ragEvidence": extract_list(
            planner_result.get("llmOutput") or {},
            "ragEvidence",
        ),
        "warnings": warnings,
        "errors": errors,
    }
    summary["safetyEvaluation"] = build_log_analysis_safety_evaluation(
        summary
    )
    summary["evidenceTrace"] = build_log_analysis_evidence_trace(summary)
    write_agent_artifacts(
        log_dir,
        summary,
        planner_result,
        retrieved,
        [analyzer_result],
    )
    report = report_renderer.render_log_analysis_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 0 if not errors else 1


def call_log_planner(
    source_summary: dict[str, Any],
    analysis_text: str,
    retrieved: list[dict[str, Any]],
    deterministic_analysis: dict[str, Any],
) -> dict[str, Any]:
    llm_input = {
        "mode": "log-analysis",
        "summary": source_summary,
        "analysisMd": analysis_text,
        "retrievedDocs": retrieved,
        "deterministicAnalysis": deterministic_analysis,
    }
    primary = deterministic_analysis.get("primaryClassification") or {}
    if primary.get("type") != "unknown":
        return deterministic_log_result(
            llm_input,
            deterministic_analysis,
            reason="Known classification from validated log evidence.",
        )
    try:
        output, exact_input, raw = analyze_log_with_llm(
            source_summary,
            analysis_text,
            retrieved,
        )
        validate_llm_output_schema("log-analysis", output, raw)
        return llm_result(True, exact_input, output, raw)
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM planner failed."
        print(f"LLM planner failed: {message}")
        return deterministic_log_result(
            llm_input,
            deterministic_analysis,
            reason=message,
            raw=raw_from_exception(exc),
        )


def deterministic_log_result(
    llm_input: dict[str, Any],
    analysis: dict[str, Any],
    *,
    reason: str,
    raw: str = "",
) -> dict[str, Any]:
    primary = analysis.get("primaryClassification") or {}
    status = str(analysis.get("status") or "unknown")
    output = {
        "decision": "failed" if status == "failed" else "succeeded",
        "classification": str(primary.get("type") or "unknown"),
        "rootCause": str(
            primary.get("cause")
            or "로그에서 확정적인 원인을 찾지 못했습니다."
        ),
        "evidence": deterministic_evidence(analysis),
        "recommendedFixes": [
            str(
                primary.get("resolution")
                or "실패 단계의 stdout/stderr를 확인해 주세요."
            )
        ],
        "rerunCommand": str(analysis.get("recommendedCommand") or ""),
        "explanationForBeginner": beginner_log_explanation(
            status,
            str(primary.get("type") or "unknown"),
        ),
    }
    result = llm_result(False, llm_input, output, raw)
    result.update(
        {
            "effectivePlanner": "deterministic-log-analyzer",
            "fallbackUsed": True,
            "fallbackReason": reason,
        }
    )
    return result


def deterministic_evidence(analysis: dict[str, Any]) -> list[str]:
    evidence = []
    if analysis.get("failedStep"):
        evidence.append(f"failedStep={analysis['failedStep']}")
    for line in str(analysis.get("evidence") or "").splitlines():
        if line.strip():
            evidence.append(line.strip())
        if len(evidence) >= 6:
            break
    return evidence or ["summary.json과 analysis.md를 규칙 기반으로 검사했습니다."]


def beginner_log_explanation(status: str, classification: str) -> str:
    if status != "failed":
        return "필수 작업은 완료됐습니다. 경고가 있다면 아래 내용을 확인해 주세요."
    if classification == "incomplete-requirement":
        return "코드 문제가 아니라 요구사항 정보가 부족해 중단된 작업입니다. 누락된 항목을 보완하면 됩니다."
    return "실패 로그에서 확인된 원인과 가장 작은 수정 방법을 아래에 정리했습니다."
