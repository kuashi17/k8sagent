"""LLM planner functions for requirement planning and log analysis."""

from __future__ import annotations

import json
import re
from typing import Any

from agent.llm.client import LLMConfig, chat_json
from agent.llm.prompts import (
    LOG_ANALYSIS_PLANNER_PROMPT,
    REQUIREMENT_PLANNER_PROMPT,
    SYSTEM_PROMPT,
    TOOL_RESULT_EVALUATION_PROMPT,
)


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


def evaluate_tool_results_with_llm(
    requirement_summary: dict[str, Any],
    planned_steps: list[Any],
    tool_calls: list[dict[str, Any]],
    validated_tool_calls: list[dict[str, Any]],
    rejected_tool_calls: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
    generated_files: dict[str, Any],
    warnings: list[str],
    errors: list[str],
    config: LLMConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    compact_results = compact_tool_results(tool_results)
    llm_input = {
        "mode": "tool-result-evaluation",
        "requirementSummary": requirement_summary,
        "plannedSteps": planned_steps,
        "toolCalls": tool_calls,
        "validatedToolCalls": validated_tool_calls,
        "rejectedToolCalls": rejected_tool_calls,
        "toolResults": compact_results,
        "generatedFiles": generated_files,
        "warnings": warnings,
        "errors": errors,
    }
    prompt = TOOL_RESULT_EVALUATION_PROMPT.format(
        requirement_summary=json.dumps(requirement_summary, ensure_ascii=False, indent=2),
        planned_steps=json.dumps(planned_steps, ensure_ascii=False, indent=2),
        tool_calls=json.dumps(tool_calls, ensure_ascii=False, indent=2),
        validated_tool_calls=json.dumps(validated_tool_calls, ensure_ascii=False, indent=2),
        rejected_tool_calls=json.dumps(rejected_tool_calls, ensure_ascii=False, indent=2),
        tool_results=json.dumps(compact_results, ensure_ascii=False, indent=2),
        generated_files=json.dumps(generated_files, ensure_ascii=False, indent=2),
        warnings=json.dumps(warnings, ensure_ascii=False, indent=2),
        errors=json.dumps(errors, ensure_ascii=False, indent=2),
    )
    raw = chat_json(SYSTEM_PROMPT, prompt, config)
    return normalize_tool_result_evaluation(parse_json_object(raw), llm_input), llm_input, raw


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


def compact_tool_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = []
    for item in results:
        stdout = str(item.get("stdout") or "")
        stderr = str(item.get("stderr") or "")
        compacted_item = {
            "tool": item.get("tool"),
            "command": item.get("command"),
            "cwd": item.get("cwd"),
            "status": item.get("status"),
            "exitCode": item.get("exitCode"),
            "stdoutSummary": summarize_tool_stdout(str(item.get("tool") or ""), stdout),
            "stderrSummary": tail_text(stderr, 500),
        }
        if item.get("steps"):
            compacted_item["steps"] = [
                {
                    "target": step.get("target"),
                    "status": step.get("status"),
                    "exitCode": step.get("exitCode"),
                }
                for step in item.get("steps") or []
            ]
        compacted.append(compacted_item)
    return compacted


def summarize_tool_stdout(tool: str, stdout: str) -> str:
    if tool == "validation":
        return "Validation Tool ran the allowlisted make targets. See steps for per-target status."
    lines = [line for line in stdout.splitlines() if line.strip()]
    selected = []
    for line in lines:
        if any(marker in line for marker in ("Spec written:", "Command plan written:", "Artifact patch completed:", "Logs:", "Target project directory:", "Dry-run mode")):
            selected.append(line)
    if selected:
        return "\n".join(selected[:12])
    return tail_text(stdout, 500)


def tail_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def normalize_tool_result_evaluation(data: dict[str, Any], llm_input: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    tool_results = llm_input.get("toolResults") or []
    rejected = llm_input.get("rejectedToolCalls") or []
    errors = llm_input.get("errors") or []
    warnings = llm_input.get("warnings") or []

    decision = str(normalized.get("executionDecision") or normalized.get("decision") or "").strip()
    if decision not in {"succeeded", "failed", "partially-succeeded"}:
        if any(item.get("exitCode") not in (0, None) for item in tool_results) or errors:
            decision = "failed"
        elif rejected:
            decision = "partially-succeeded"
        else:
            decision = "succeeded"
        normalized["executionDecision"] = decision

    completed = normalized.get("completedSteps")
    if not isinstance(completed, list):
        normalized["completedSteps"] = [
            str(item.get("tool")) for item in tool_results if item.get("exitCode") == 0 and item.get("tool")
        ]
    else:
        normalized["completedSteps"] = stringify_items(completed, preferred_keys=["tool", "name", "step"])

    failed = normalized.get("failedSteps")
    if not isinstance(failed, list):
        failed_steps = [
            str(item.get("tool")) for item in tool_results if item.get("exitCode") not in (0, None) and item.get("tool")
        ]
        failed_steps.extend(str(item.get("tool") or item.get("reason") or "rejected tool call") for item in rejected)
        normalized["failedSteps"] = failed_steps
    else:
        normalized["failedSteps"] = stringify_items(failed, preferred_keys=["tool", "name", "step", "reason"])

    artifacts = normalized.get("generatedArtifacts")
    generated_files = llm_input.get("generatedFiles") or {}
    generated_paths = [str(value) for value in generated_files.values() if value]
    if not isinstance(artifacts, list) or not artifacts:
        normalized["generatedArtifacts"] = generated_paths
    else:
        artifact_values = stringify_items(artifacts, preferred_keys=["path", "name"])
        for path in generated_paths:
            if path not in artifact_values:
                artifact_values.append(path)
        normalized["generatedArtifacts"] = artifact_values

    validation_results = normalized.get("validationResults")
    inferred_validation = infer_validation_results(tool_results)
    if not isinstance(validation_results, dict):
        normalized["validationResults"] = inferred_validation
    else:
        if all(value == "skipped" for value in inferred_validation.values()):
            normalized["validationResults"] = inferred_validation
        else:
            inferred = inferred_validation
            normalized["validationResults"] = {
                "makeGenerate": normalize_validation_status(validation_results.get("makeGenerate"), inferred["makeGenerate"]),
                "makeManifests": normalize_validation_status(validation_results.get("makeManifests"), inferred["makeManifests"]),
                "makeTest": normalize_validation_status(validation_results.get("makeTest"), inferred["makeTest"]),
            }

    evidence = normalized.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        normalized["evidence"] = [
            f"{item.get('tool')} exitCode={item.get('exitCode')} status={item.get('status')}" for item in tool_results
        ]
    else:
        normalized["evidence"] = stringify_items(evidence, preferred_keys=["summary", "tool", "path", "name"])

    if not isinstance(normalized.get("warnings"), list):
        normalized["warnings"] = list(warnings)
    if not isinstance(normalized.get("recommendedNextActions"), list):
        if decision == "succeeded":
            normalized["recommendedNextActions"] = ["생성된 operator-spec.yaml과 command plan을 검토한 뒤 scaffold execute 단계로 진행합니다."]
        elif decision == "partially-succeeded":
            normalized["recommendedNextActions"] = ["거부된 Tool 호출 이유를 확인하고, 안전 조건을 만족하도록 계획을 조정합니다."]
        else:
            normalized["recommendedNextActions"] = ["실패한 Tool의 stderr와 관련 로그를 확인한 뒤 해당 단계부터 재실행합니다."]

    if not normalized.get("beginnerSummary"):
        normalized["beginnerSummary"] = (
            "요구사항을 구조화하고 실행 계획을 만든 뒤, 허용된 Tool을 안전 모드로 실행했습니다. "
            "각 Tool의 exitCode와 생성 파일을 기준으로 최종 상태를 판단했습니다."
        )

    return normalized


def infer_validation_results(tool_results: list[dict[str, Any]]) -> dict[str, str]:
    result = {"makeGenerate": "skipped", "makeManifests": "skipped", "makeTest": "skipped"}
    key_by_target = {"generate": "makeGenerate", "manifests": "makeManifests", "test": "makeTest"}
    for item in tool_results:
        if item.get("tool") != "validation":
            continue
        for step in item.get("steps") or []:
            target = step.get("target")
            key = key_by_target.get(str(target))
            if key:
                result[key] = "succeeded" if step.get("exitCode") == 0 else "failed"
    return result


def normalize_validation_status(value: Any, fallback: str) -> str:
    if value in {"succeeded", "failed", "skipped"}:
        return str(value)
    return fallback


def stringify_items(items: list[Any], preferred_keys: list[str]) -> list[str]:
    values: list[str] = []
    for item in items:
        if isinstance(item, dict):
            selected = ""
            for key in preferred_keys:
                if item.get(key):
                    selected = str(item[key])
                    break
            if not selected:
                selected = json.dumps(item, ensure_ascii=False)
            values.append(selected)
        else:
            values.append(str(item))
    return values


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
