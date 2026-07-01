"""Structured Tool failure taxonomy shared by execution and recovery."""

from __future__ import annotations

import re
import json
import sys
from typing import Any

from agent.error_registry import ErrorCode, get_error_definition


def normalize_tool_result(
    result: dict[str, Any],
    tool: str = "",
) -> dict[str, Any]:
    normalized = dict(result)
    if int(normalized.get("exitCode") or 0) == 0:
        normalized["errorCode"] = ""
        normalized.pop("errorDetails", None)
        return normalized
    native = extract_native_error(normalized)
    if native:
        details = canonical_error_details(native)
        normalized["errorCode"] = details["errorCode"]
        normalized["errorDetails"] = details
        return normalized
    existing = str(normalized.get("errorCode") or "")
    details = normalized.get("errorDetails")
    if existing and isinstance(details, dict):
        canonical = canonical_error_details(
            {**details, "errorCode": existing}
        )
        normalized["errorDetails"] = canonical
        return normalized
    structured = infer_tool_error(normalized, tool)
    normalized["errorCode"] = structured["errorCode"]
    normalized["errorDetails"] = structured
    return normalized


def emit_tool_error(
    error_code: ErrorCode | str,
    message: str,
    *,
    stage: str = "",
    resource: str = "",
    verb: str = "",
) -> dict[str, Any]:
    code = error_code.value if isinstance(error_code, ErrorCode) else str(error_code)
    contract = get_error_definition(code)
    payload = {
        "errorCode": code,
        "category": contract.category,
        "message": message,
        "userMessage": contract.userMessage,
        "recoveryPolicy": contract.recoveryPolicy,
        "uiSeverity": contract.uiSeverity,
        "stage": stage,
        "resource": resource,
        "verb": verb,
        "retryable": contract.retryable,
    }
    print(
        "TOOL_ERROR_JSON=" + json.dumps(payload, ensure_ascii=False),
        file=sys.stderr,
    )
    return payload


def extract_native_error(result: dict[str, Any]) -> dict[str, Any] | None:
    summary = result.get("deploymentSummary") or {}
    if summary.get("errorCode") and isinstance(summary.get("errorDetails"), dict):
        return dict(summary["errorDetails"])
    text = "\n".join(
        [
            str(result.get("stderr") or ""),
            str(result.get("stdout") or ""),
        ]
    )
    for line in reversed(text.splitlines()):
        if not line.startswith("TOOL_ERROR_JSON="):
            continue
        try:
            payload = json.loads(line.split("=", 1)[1])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("errorCode"):
            return payload
    return None


def infer_tool_error(
    result: dict[str, Any],
    tool: str = "",
) -> dict[str, Any]:
    summary = result.get("deploymentSummary") or {}
    failed_step = str(summary.get("failedStep") or failed_result_step(result))
    text = " ".join(
        [
            str(result.get("stderr") or ""),
            str(result.get("stdout") or ""),
            str((summary.get("checks") or {}).get("error") or ""),
            str(summary.get("error") or ""),
        ]
    )
    lowered = text.lower()
    code = ErrorCode.UNKNOWN
    if "cannot connect to the docker daemon" in lowered or "docker daemon" in lowered:
        code = ErrorCode.DOCKER_DAEMON_UNAVAILABLE
    elif "timed out" in lowered or "timeout" in lowered:
        code = ErrorCode.COMMAND_TIMEOUT
    elif "forbidden" in lowered or failed_step == "rbac-preflight":
        code = ErrorCode.RBAC_FORBIDDEN
    elif "insufficient nvidia.com/gpu" in lowered:
        code = ErrorCode.GPU_INSUFFICIENT
    elif "imagepull" in lowered or "image pull" in lowered:
        code = ErrorCode.IMAGE_PULL_FAILED
    elif "persistentvolumeclaim" in lowered and "not found" in lowered:
        code = ErrorCode.PVC_NOT_FOUND
    elif "not found" in lowered:
        code = ErrorCode.KUBERNETES_RESOURCE_NOT_FOUND
    elif "unsupported make targets" in lowered:
        code = ErrorCode.VALIDATION_TARGET_DENIED
    elif "unsupported type" in lowered or "field type" in lowered:
        code = ErrorCode.INVALID_FIELD_TYPE
    elif "outside the project root" in lowered or "outside repository" in lowered:
        code = ErrorCode.PATH_POLICY_VIOLATION
    elif "missing required" in lowered:
        code = ErrorCode.REQUIRED_INPUT_MISSING
    elif tool == "validation" or failed_step.startswith("make "):
        code = ErrorCode.VALIDATION_FAILED
    elif tool == "kind_deployment" and "connection" in lowered:
        code = ErrorCode.KIND_CONNECTION_FAILED
    resource, verb = extract_rbac_subject(text)
    return canonical_error_details({
        "errorCode": code.value,
        "message": concise_message(text, code.value),
        "stage": failed_step or tool,
        "resource": resource,
        "verb": verb,
    })


def classification_for_error_code(value: Any) -> str:
    if not value:
        return ""
    return get_error_definition(str(value)).recoveryClassification


def error_category(code: ErrorCode) -> str:
    return get_error_definition(code).category


def canonical_error_details(payload: dict[str, Any]) -> dict[str, Any]:
    code = str(payload.get("errorCode") or ErrorCode.UNKNOWN.value)
    contract = get_error_definition(code)
    return {
        **payload,
        "errorCode": code,
        "category": contract.category,
        "userMessage": contract.userMessage,
        "recoveryPolicy": contract.recoveryPolicy,
        "uiSeverity": contract.uiSeverity,
        "retryable": contract.retryable,
    }


def failed_result_step(result: dict[str, Any]) -> str:
    for step in result.get("steps") or []:
        if int(step.get("exitCode") or 0) != 0:
            return f"make {step.get('target') or step.get('name') or 'validation'}"
    return ""


def extract_rbac_subject(text: str) -> tuple[str, str]:
    verb_match = re.search(
        r"(?:cannot|denied:?|forbidden.*?)(?:\s+to)?\s+(get|list|watch|create|update|patch|delete)\s+([a-z0-9./-]+)",
        text,
        re.IGNORECASE,
    )
    if verb_match:
        return verb_match.group(2), verb_match.group(1).lower()
    resource = re.search(r'resource[s]?[=:" ]+([a-z0-9./-]+)', text, re.IGNORECASE)
    verb = re.search(r'verb[=:" ]+([a-z]+)', text, re.IGNORECASE)
    return (
        resource.group(1) if resource else "",
        verb.group(1).lower() if verb else "",
    )


def concise_message(text: str, fallback: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[-1] if lines else fallback)[:1000]
