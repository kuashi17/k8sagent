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
    )

    errors = (
        []
        if analyzer_result["exitCode"] == 0
        else ["log_analyzer failed"]
    )
    if planner_result["error"]:
        errors.append("LLM planner failed")

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
        "warnings": source_summary.get("warnings") or [],
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
) -> dict[str, Any]:
    llm_input = {
        "mode": "log-analysis",
        "summary": source_summary,
        "analysisMd": analysis_text,
        "retrievedDocs": retrieved,
    }
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
        return llm_result(
            False,
            llm_input,
            {},
            raw_from_exception(exc),
            message,
        )
