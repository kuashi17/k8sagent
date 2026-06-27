"""LLM planner functions for requirement planning and log analysis."""

from __future__ import annotations

import json
import os
import re
from dataclasses import replace
from typing import Any

from agent.llm.client import LLMConfig, chat_json, config_from_env
from agent.llm.prompts import (
    LOG_ANALYSIS_PLANNER_PROMPT,
    RECOVERY_PLANNER_PROMPT,
    REQUIREMENT_PLAN_REPAIR_PROMPT,
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
    intent_analysis: dict[str, Any] | None = None,
    profile_candidates: list[dict[str, Any]] | None = None,
    workflow_options: dict[str, Any] | None = None,
    config: LLMConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    compact_docs = compact_retrieved_docs(retrieved_docs, excerpt_limit=320)
    compact_intent = compact_intent_analysis(intent_analysis or {})
    compact_profile = compact_profile_summary(profile_summary)
    compact_candidates = [compact_profile_summary(item) for item in (profile_candidates or [])[:2]]
    llm_input = {
        "mode": "requirement-planning",
        "requirementText": requirement_text,
        "retrievedDocs": compact_docs,
        "intentAnalysis": intent_analysis or {},
        "profileSummary": profile_summary,
        "profileCandidates": profile_candidates or [],
        "workflowOptions": workflow_options or {},
        "safetyMode": safety_mode,
    }
    prompt = REQUIREMENT_PLANNER_PROMPT.format(
        requirement_text=requirement_text,
        retrieved_docs=compact_json(compact_docs),
        intent_analysis=compact_json(compact_intent),
        profile_summary=compact_json(compact_profile),
        profile_candidates=compact_json(compact_candidates),
        workflow_options=compact_json(workflow_options or {}),
        tool_call_examples=requirement_tool_call_examples(
            safety_mode,
            bool((workflow_options or {}).get("kindDeploymentRequested")),
        ),
        kind_deployment_rule=(
            "- kind_deployment was explicitly requested. Include it after validation."
            if (workflow_options or {}).get("kindDeploymentRequested")
            else "- kind_deployment is not available in this request. Do not include it."
        ),
        safety_mode=safety_mode,
    )
    planning_config = requirement_planning_config(config)
    raw = chat_json(SYSTEM_PROMPT, prompt, planning_config)
    parsed = normalize_requirement_plan(parse_json_object(raw), profile_summary)
    errors = requirement_plan_validation_errors(parsed)
    if not errors:
        return parsed, llm_input, raw

    repair_prompt = REQUIREMENT_PLAN_REPAIR_PROMPT.format(
        optional_kind_tool_name=", kind_deployment" if (workflow_options or {}).get("kindDeploymentRequested") else "",
        safety_mode=safety_mode,
        workflow_options=compact_json(workflow_options or {}),
        validation_errors="; ".join(errors),
        candidate=raw[:6000],
    )
    repaired_raw = chat_json(SYSTEM_PROMPT, repair_prompt, planning_config)
    repaired = normalize_requirement_plan(parse_json_object(repaired_raw), profile_summary)
    llm_input["responseRepair"] = {
        "attempted": True,
        "validationErrors": errors,
        "originalRawOutput": raw,
    }
    return repaired, llm_input, repaired_raw


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
    compact_validated = [
        {
            "tool": item.get("tool"),
            "effectiveMode": item.get("effectiveMode"),
        }
        for item in validated_tool_calls
    ]
    llm_input = {
        "mode": "tool-result-evaluation",
        "requirementSummary": requirement_summary,
        "validatedToolCalls": compact_validated,
        "rejectedToolCalls": rejected_tool_calls,
        "toolResults": compact_results,
        "generatedFiles": generated_files,
        "warnings": warnings,
        "errors": errors,
    }
    prompt = TOOL_RESULT_EVALUATION_PROMPT.format(
        requirement_summary=compact_json(requirement_summary),
        validated_tool_calls=compact_json(compact_validated),
        rejected_tool_calls=compact_json(rejected_tool_calls),
        tool_results=compact_json(compact_results),
        warnings=compact_json(warnings),
        errors=compact_json(errors),
    )
    raw = chat_json(
        SYSTEM_PROMPT,
        prompt,
        config or config_from_env(purpose="final"),
    )
    return normalize_tool_result_evaluation(parse_json_object(raw), llm_input), llm_input, raw


def plan_recovery_with_llm(
    requirement_summary: dict[str, Any],
    tool_plan: list[dict[str, Any]],
    successful_tool_results: list[dict[str, Any]],
    failed_tool_result: dict[str, Any],
    failure_context: dict[str, Any],
    retrieved_docs: list[dict[str, Any]],
    agent_mode: str,
    config: LLMConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    compact_success = compact_tool_results(successful_tool_results)
    compact_failed = compact_tool_results([failed_tool_result])[0] if failed_tool_result else {}
    compact_docs = compact_retrieved_docs(retrieved_docs, excerpt_limit=700)
    llm_input = {
        "mode": "recovery-planning",
        "requirementSummary": requirement_summary,
        "toolPlan": tool_plan,
        "successfulToolResults": compact_success,
        "failedToolResult": compact_failed,
        "failureContext": failure_context,
        "retrievedDocs": compact_docs,
        "agentMode": agent_mode,
    }
    prompt = RECOVERY_PLANNER_PROMPT.format(
        requirement_summary=json.dumps(requirement_summary, ensure_ascii=False, indent=2),
        tool_plan=json.dumps(tool_plan, ensure_ascii=False, indent=2),
        successful_tool_results=json.dumps(compact_success, ensure_ascii=False, indent=2),
        failed_tool_result=json.dumps(compact_failed, ensure_ascii=False, indent=2),
        failure_context=json.dumps(failure_context, ensure_ascii=False, indent=2),
        retrieved_docs=json.dumps(compact_docs, ensure_ascii=False, indent=2),
        agent_mode=agent_mode,
    )
    raw = chat_json(SYSTEM_PROMPT, prompt, config)
    return normalize_recovery_plan(parse_json_object(raw), failure_context), llm_input, raw


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


def normalize_requirement_plan(
    data: dict[str, Any],
    profile_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = dict(data)
    aliases = {
        "tool_calls": "toolCalls",
        "tools": "toolCalls",
        "missing_information": "missingInformation",
        "steps": "plannedSteps",
        "next_actions": "nextActions",
        "profile": "recommendedProfile",
        "summary": "requirementSummary",
    }
    for source, target in aliases.items():
        if target not in normalized and source in normalized:
            normalized[target] = normalized[source]
    tool_calls = normalized.get("toolCalls")
    planned_steps = normalized.get("plannedSteps")
    if not isinstance(tool_calls, list) and isinstance(planned_steps, list):
        inferred = [
            item
            for item in planned_steps
            if isinstance(item, dict) and item.get("tool") and item.get("mode")
        ]
        if inferred:
            normalized["toolCalls"] = inferred
            normalized["plannedSteps"] = [
                str(item.get("reason") or item.get("tool"))
                if isinstance(item, dict)
                else str(item)
                for item in planned_steps
            ]
    for key in ("missingInformation", "plannedSteps", "risks", "nextActions"):
        if key not in normalized or normalized[key] is None:
            normalized[key] = []
    if not isinstance(normalized.get("recommendedProfile"), str):
        normalized["recommendedProfile"] = str((profile_summary or {}).get("path") or "")
    return normalized


def requirement_plan_validation_errors(data: dict[str, Any]) -> list[str]:
    schema = {
        "requirementSummary": str,
        "missingInformation": list,
        "recommendedProfile": str,
        "plannedSteps": list,
        "toolCalls": list,
        "risks": list,
        "nextActions": list,
    }
    errors = []
    for key, expected in schema.items():
        if key not in data:
            errors.append(f"missing {key}")
        elif not isinstance(data[key], expected):
            errors.append(f"{key} must be {expected.__name__}")
    if isinstance(data.get("toolCalls"), list):
        if not data["toolCalls"]:
            errors.append("toolCalls must not be empty")
        for index, item in enumerate(data["toolCalls"]):
            if not isinstance(item, dict):
                errors.append(f"toolCalls[{index}] must be object")
                continue
            for key in ("tool", "mode"):
                if not item.get(key):
                    errors.append(f"toolCalls[{index}] missing {key}")
    return errors


def requirement_planning_config(config: LLMConfig | None) -> LLMConfig:
    cfg = config or config_from_env(purpose="planning")
    raw = os.environ.get("LOCAL_LLM_PLANNING_MAX_TOKENS", "460")
    try:
        max_tokens = max(320, int(raw))
    except ValueError:
        max_tokens = 460
    return replace(cfg, max_tokens=min(cfg.max_tokens, max_tokens))


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def compact_intent_analysis(intent: dict[str, Any]) -> dict[str, Any]:
    return {
        "primaryIntent": intent.get("primaryIntent", ""),
        "managedResourceHints": intent.get("managedResourceHints") or [],
        "confidence": intent.get("confidence", ""),
    }


def compact_profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": profile.get("path", ""),
        "name": profile.get("name", ""),
        "managedResources": profile.get("managedResources") or [],
        "selectionMode": profile.get("selectionMode", ""),
    }


def requirement_tool_call_examples(safety_mode: str, include_kind: bool) -> str:
    calls = [
        {"tool": "spec_generator", "mode": "generate", "reason": "Generate the Operator spec."},
        {
            "tool": "capability_drafter",
            "mode": "execute" if safety_mode == "execute" else "dry-run",
            "reason": "Validate managed resource capabilities.",
        },
        {"tool": "command_planner", "mode": "dry-run", "reason": "Plan allowlisted commands."},
        {
            "tool": "scaffold_runner",
            "mode": "execute" if safety_mode == "execute" else "dry-run",
            "reason": "Create the Kubebuilder scaffold.",
        },
    ]
    if safety_mode == "execute":
        calls.extend(
            [
                {"tool": "artifact_patcher", "mode": "execute", "reason": "Apply requirement fields and controller logic."},
                {"tool": "validation", "mode": "execute", "reason": "Run generate, manifests, and tests."},
            ]
        )
    if include_kind:
        calls.append(
            {
                "tool": "kind_deployment",
                "mode": "execute" if safety_mode == "execute" else "dry-run",
                "reason": "Deploy to kind after validation.",
            }
        )
    return ",\n    ".join(compact_json(item) for item in calls)


def compact_retrieved_docs(docs: list[dict[str, Any]], excerpt_limit: int = 900) -> list[dict[str, Any]]:
    compacted = []
    for item in docs:
        compacted.append(
            {
                "path": item.get("path", ""),
                "sourcePath": item.get("sourcePath", item.get("path", "")),
                "title": item.get("title", ""),
                "category": item.get("category", ""),
                "matchedKeywords": (item.get("matchedKeywords") or [])[:20],
                "excerpt": str(item.get("excerpt", ""))[:excerpt_limit],
                "score": item.get("score"),
                "vectorScore": item.get("vectorScore"),
                "keywordScore": item.get("keywordScore"),
                "combinedScore": item.get("combinedScore"),
                "rerankScore": item.get("rerankScore"),
                "rerankReason": item.get("reason"),
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
        if item.get("deploymentSummary"):
            deployment = item.get("deploymentSummary") or {}
            checks = deployment.get("checks") or {}
            compacted_item["deploymentSummary"] = {
                "status": deployment.get("status"),
                "failedStep": deployment.get("failedStep"),
                "clusterName": deployment.get("clusterName"),
                "validator": deployment.get("validator") or {},
                "checks": {
                    key: value
                    for key, value in checks.items()
                    if key
                    in {
                        "controllerDeployment",
                        "managedResource",
                        "customResourceStatus",
                        "lifecycleUpdate",
                        "lifecycleDisabled",
                        "lifecycleDelete",
                        "lifecycleRestore",
                        "error",
                    }
                },
                "elapsedSeconds": deployment.get("elapsedSeconds"),
                "logDir": deployment.get("logDir"),
            }
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


def normalize_recovery_plan(data: dict[str, Any], failure_context: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    decision = str(normalized.get("decision") or "").strip()
    if decision not in {"recovery-required", "manual-review-required", "unrecoverable"}:
        decision = "recovery-required" if failure_context.get("failedTool") else "manual-review-required"
    normalized["decision"] = decision

    if not normalized.get("classification"):
        normalized["classification"] = classify_failure_context(failure_context)
    if not normalized.get("rootCause"):
        stderr = str(failure_context.get("stderrTail") or "")
        stdout = str(failure_context.get("stdoutTail") or "")
        normalized["rootCause"] = first_nonempty_line(stderr) or first_nonempty_line(stdout) or "실패 로그에서 원인을 명확히 찾지 못했습니다."
    if not isinstance(normalized.get("evidence"), list) or not normalized["evidence"]:
        evidence = []
        if failure_context.get("failedTool"):
            evidence.append(f"failedTool={failure_context.get('failedTool')}")
        if failure_context.get("exitCode") is not None:
            evidence.append(f"exitCode={failure_context.get('exitCode')}")
        if failure_context.get("failedStep"):
            evidence.append(f"failedStep={failure_context.get('failedStep')}")
        normalized["evidence"] = evidence
    if not isinstance(normalized.get("proposedFixes"), list) or not normalized["proposedFixes"]:
        normalized["proposedFixes"] = default_recovery_fixes(normalized["classification"])

    calls = normalized.get("recoveryToolCalls")
    if not isinstance(calls, list):
        calls = []
    safe_calls = []
    for item in calls:
        if not isinstance(item, dict):
            continue
        item = dict(item)
        item["requiresApproval"] = True
        safe_calls.append(item)
    if not safe_calls:
        failed_tool = failure_context.get("failedTool") or "validation"
        safe_calls = [
            {
                "tool": failed_tool,
                "mode": "dry-run",
                "reason": "Validate the proposed fix after the user approves changes.",
                "requiresApproval": True,
            }
        ]
    normalized["recoveryToolCalls"] = safe_calls

    if not normalized.get("rerunFromStep"):
        normalized["rerunFromStep"] = str(failure_context.get("failedTool") or failure_context.get("failedStep") or "failed step")
    risks = normalized.get("risks")
    if not isinstance(risks, list):
        normalized["risks"] = ["복구 Tool은 사용자 승인 전 실행되지 않습니다."]
    if not normalized.get("beginnerSummary"):
        normalized["beginnerSummary"] = "Agent가 실패 단계와 로그를 분석했고, 자동 수정 없이 복구 계획만 작성했습니다."
    return normalized


def classify_failure_context(failure_context: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(failure_context.get("failedTool") or ""),
            str(failure_context.get("failedStep") or ""),
            str(failure_context.get("stdoutTail") or ""),
            str(failure_context.get("stderrTail") or ""),
        ]
    ).lower()
    if "undefined" in text or "notatype" in text or "cannot use" in text:
        return "go-build-test-failure"
    if "forbidden" in text or "rbac" in text:
        return "rbac-forbidden"
    if "no such file" in text or "not found" in text:
        return "missing-artifact"
    if "make" in text:
        return "make-validation-failure"
    return "unknown"


def default_recovery_fixes(classification: str) -> list[str]:
    if classification == "go-build-test-failure":
        return ["operator-spec.yaml의 필드 타입을 Go/Kubernetes CRD에서 지원되는 타입으로 수정한 뒤 artifact patch와 validation을 다시 실행합니다."]
    if classification == "rbac-forbidden":
        return ["controller RBAC marker와 config/rbac/role.yaml에 필요한 resource/verbs가 있는지 확인합니다."]
    if classification == "missing-artifact":
        return ["scaffold가 성공적으로 생성한 프로젝트 경로와 artifact_patcher의 --project 경로가 일치하는지 확인합니다."]
    return ["실패한 Tool의 stderr/stdout 로그를 확인하고 해당 단계부터 복구합니다."]


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


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
        profile = (summary.get("profileConfig") or {}).get("profilePath")
        if project and cluster and sample and profile:
            normalized["rerunCommand"] = (
                "python3 agent/tools/e2e_runner.py "
                f"--profile {profile} --project {project} "
                f"--cluster-name {cluster} --sample {sample} "
                "--clean --execute"
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
