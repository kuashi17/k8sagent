"""LLM planner functions for requirement planning and log analysis."""

from __future__ import annotations

import json
import re
from typing import Any

from agent.llm.client import LLMConfig, chat_json
from agent.llm.prompts import LOG_ANALYSIS_PLANNER_PROMPT, REQUIREMENT_PLANNER_PROMPT, SYSTEM_PROMPT


class LLMOutputParseError(ValueError):
    """Raised when a local LLM response cannot be parsed as JSON."""

    def __init__(self, message: str, raw_output: str):
        super().__init__(message)
        self.raw_output = raw_output


def plan_requirement_with_llm(
    requirement_text: str,
    retrieved_docs: list[dict[str, Any]],
    profile_summary: dict[str, Any],
    safety_mode: str,
    config: LLMConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    compact_docs = compact_retrieved_docs(retrieved_docs)
    llm_input = {
        "mode": "requirement-planning",
        "requirementText": requirement_text,
        "retrievedDocs": compact_docs,
        "profileSummary": profile_summary,
        "safetyMode": safety_mode,
    }
    prompt = REQUIREMENT_PLANNER_PROMPT.format(
        requirement_text=requirement_text,
        retrieved_docs=json.dumps(compact_docs, ensure_ascii=False, indent=2),
        profile_summary=json.dumps(profile_summary, ensure_ascii=False, indent=2),
        safety_mode=safety_mode,
    )
    raw = chat_json(SYSTEM_PROMPT, prompt, config)
    return parse_json_object(raw), llm_input, raw


def analyze_log_with_llm(
    summary: dict[str, Any],
    analysis_md: str,
    retrieved_docs: list[dict[str, Any]],
    config: LLMConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    compact_summary = compact_execution_summary(summary)
    compact_analysis = analysis_md[:6000]
    compact_docs = compact_retrieved_docs(retrieved_docs, excerpt_limit=700)
    llm_input = {
        "mode": "log-analysis",
        "summary": compact_summary,
        "analysisMd": compact_analysis,
        "retrievedDocs": compact_docs,
    }
    prompt = LOG_ANALYSIS_PLANNER_PROMPT.format(
        summary_json=json.dumps(compact_summary, ensure_ascii=False, indent=2),
        analysis_md=compact_analysis,
        retrieved_docs=json.dumps(compact_docs, ensure_ascii=False, indent=2),
    )
    raw = chat_json(SYSTEM_PROMPT, prompt, config)
    return normalize_log_analysis_output(parse_json_object(raw), compact_summary), llm_input, raw


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    candidates = [text]

    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if code_block:
        candidates.append(code_block.group(1).strip())

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and first < last:
        candidates.append(text[first : last + 1])

    data: Any = None
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError as exc:
            last_error = exc
    else:
        raise LLMOutputParseError(f"LLM output could not be parsed as JSON: {last_error}", raw)

    if not isinstance(data, dict):
        raise LLMOutputParseError("LLM output must be a JSON object.", raw)
    return data


def compact_retrieved_docs(docs: list[dict[str, Any]], excerpt_limit: int = 900) -> list[dict[str, Any]]:
    compacted = []
    for item in docs:
        compacted.append(
            {
                "path": item.get("path", ""),
                "title": item.get("title", ""),
                "matchedKeywords": (item.get("matchedKeywords") or [])[:20],
                "excerpt": str(item.get("excerpt", ""))[:excerpt_limit],
                "score": item.get("score"),
            }
        )
    return compacted


def compact_execution_summary(summary: dict[str, Any]) -> dict[str, Any]:
    steps = []
    for item in summary.get("steps") or []:
        if not isinstance(item, dict):
            continue
        steps.append(
            {
                "name": item.get("name"),
                "status": item.get("status"),
                "exitCode": item.get("exitCode"),
                "command": item.get("command"),
            }
        )
    return {
        "mode": summary.get("mode"),
        "projectDir": summary.get("projectDir"),
        "clusterName": summary.get("clusterName"),
        "sample": summary.get("sample"),
        "failedStep": summary.get("failedStep"),
        "warnings": summary.get("warnings") or [],
        "errors": summary.get("errors") or [],
        "clean": summary.get("clean"),
        "expected": summary.get("expected") or {},
        "jobSpecValidation": summary.get("jobSpecValidation") or {},
        "profileConfig": summary.get("profileConfig") or {},
        "steps": steps[:80],
    }


def normalize_log_analysis_output(data: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    """Normalize small-model variants into the required log-analysis schema."""

    normalized = dict(data)

    if "decision" not in normalized and "type" in normalized:
        normalized["decision"] = normalized.get("type")
    if "rootCause" not in normalized and "cause" in normalized:
        normalized["rootCause"] = normalized.get("cause")
    if "recommendedFixes" not in normalized and "resolution" in normalized:
        resolution = normalized.get("resolution")
        normalized["recommendedFixes"] = [resolution] if resolution else []

    warnings = summary.get("warnings") or []
    validation = summary.get("jobSpecValidation") or {}
    failed_step = summary.get("failedStep")

    decision = str(normalized.get("decision") or "").strip()
    if decision not in {"succeeded", "failed", "succeeded-with-warning"}:
        if failed_step:
            decision = "failed"
        elif warnings:
            decision = "succeeded-with-warning"
        else:
            decision = "succeeded"
        normalized["decision"] = decision

    if not normalized.get("classification"):
        warning_text = " ".join(str(item) for item in warnings).lower()
        if "gpu" in warning_text or "nvidia.com/gpu" in warning_text:
            normalized["classification"] = "gpu-insufficient"
        elif "pending" in warning_text:
            normalized["classification"] = "pod-pending"
        elif failed_step:
            normalized["classification"] = "failed-step"
        else:
            normalized["classification"] = "success"

    if not normalized.get("rootCause"):
        if normalized["classification"] == "gpu-insufficient":
            normalized["rootCause"] = (
                "Controller와 Job spec 검증은 성공했지만, kind 클러스터에 GPU 리소스가 없어 Pod가 Pending 상태입니다."
            )
        elif failed_step:
            normalized["rootCause"] = f"실패 단계가 기록되었습니다: {failed_step}"
        else:
            normalized["rootCause"] = "실행 로그에서 실패 원인이 발견되지 않았습니다."

    evidence = normalized.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        evidence = []
        if validation:
            evidence.append(f"jobSpecValidation.passed={validation.get('passed')}")
        if warnings:
            evidence.extend(str(item) for item in warnings[:3])
        if not failed_step:
            evidence.append("summary.json failedStep is empty.")
        normalized["evidence"] = evidence

    fixes = normalized.get("recommendedFixes")
    if not isinstance(fixes, list) or not fixes:
        if normalized["classification"] == "gpu-insufficient":
            fixes = [
                "GPU 노드가 있는 클러스터에서 실행합니다.",
                "kind 검증에서는 gpuCount를 0으로 낮춘 e2e sample을 사용합니다.",
            ]
        elif failed_step:
            fixes = ["failedStep에 해당하는 명령의 stdout/stderr 로그를 확인하고 해당 산출물만 수정한 뒤 재실행합니다."]
        else:
            fixes = ["추가 수정 없이 동일 명령으로 재실행할 수 있습니다."]
        normalized["recommendedFixes"] = fixes

    if not normalized.get("rerunCommand"):
        project = summary.get("projectDir")
        cluster = summary.get("clusterName")
        sample = summary.get("sample")
        if project and cluster and sample:
            normalized["rerunCommand"] = (
                "python3 agent/tools/e2e_runner.py "
                f"--project {project} --cluster-name {cluster} --sample {sample} --clean --execute"
            )
        else:
            normalized["rerunCommand"] = "summary.json에 재실행 명령을 구성할 충분한 정보가 없어 동일 runner 명령을 수동으로 확인해야 합니다."

    if not normalized.get("explanationForBeginner"):
        if normalized["classification"] == "gpu-insufficient":
            normalized["explanationForBeginner"] = (
                "Operator가 Job을 만들지 못한 오류가 아닙니다. Job 설정 검증은 통과했고, 로컬 kind 클러스터에 GPU가 없어서 Pod만 실행 대기 상태입니다."
            )
        else:
            normalized["explanationForBeginner"] = "summary.json과 analysis.md를 기준으로 실행 결과를 요약했습니다."

    rag = normalized.get("ragEvidence")
    if not isinstance(rag, list):
        normalized["ragEvidence"] = []

    return normalized
