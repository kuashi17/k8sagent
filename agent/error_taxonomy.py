"""Structured Tool failure taxonomy shared by execution and recovery."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    NONE = ""
    UNKNOWN = "TOOL_EXECUTION_FAILED"
    TOOL_VALIDATION_REJECTED = "TOOL_VALIDATION_REJECTED"
    PATH_POLICY_VIOLATION = "PATH_POLICY_VIOLATION"
    REQUIRED_INPUT_MISSING = "REQUIRED_INPUT_MISSING"
    INVALID_FIELD_TYPE = "INVALID_FIELD_TYPE"
    CAPABILITY_UNSUPPORTED = "CAPABILITY_UNSUPPORTED"
    VALIDATION_TARGET_DENIED = "VALIDATION_TARGET_DENIED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    ARTIFACT_MISSING = "ARTIFACT_MISSING"
    RBAC_FORBIDDEN = "RBAC_FORBIDDEN"
    KUBERNETES_RESOURCE_NOT_FOUND = "KUBERNETES_RESOURCE_NOT_FOUND"
    PVC_NOT_FOUND = "PVC_NOT_FOUND"
    GPU_INSUFFICIENT = "GPU_INSUFFICIENT"
    IMAGE_PULL_FAILED = "IMAGE_PULL_FAILED"
    DOCKER_DAEMON_UNAVAILABLE = "DOCKER_DAEMON_UNAVAILABLE"
    KIND_CONNECTION_FAILED = "KIND_CONNECTION_FAILED"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"


ERROR_CLASSIFICATIONS = {
    ErrorCode.TOOL_VALIDATION_REJECTED.value: "tool-validation",
    ErrorCode.PATH_POLICY_VIOLATION.value: "path-safety",
    ErrorCode.REQUIRED_INPUT_MISSING.value: "incomplete-requirement",
    ErrorCode.INVALID_FIELD_TYPE.value: "invalid-field-type",
    ErrorCode.CAPABILITY_UNSUPPORTED.value: "unsupported-capability",
    ErrorCode.VALIDATION_TARGET_DENIED.value: "validation-target-denied",
    ErrorCode.VALIDATION_FAILED.value: "go-build-test-failure",
    ErrorCode.ARTIFACT_MISSING.value: "missing-artifact",
    ErrorCode.RBAC_FORBIDDEN.value: "rbac-forbidden",
    ErrorCode.KUBERNETES_RESOURCE_NOT_FOUND.value: "resource-not-found",
    ErrorCode.PVC_NOT_FOUND.value: "pvc-not-found",
    ErrorCode.GPU_INSUFFICIENT.value: "gpu-insufficient",
    ErrorCode.IMAGE_PULL_FAILED.value: "image-pull",
    ErrorCode.DOCKER_DAEMON_UNAVAILABLE.value: "docker-kind-connection",
    ErrorCode.KIND_CONNECTION_FAILED.value: "docker-kind-connection",
    ErrorCode.COMMAND_TIMEOUT.value: "command-timeout",
}


def normalize_tool_result(
    result: dict[str, Any],
    tool: str = "",
) -> dict[str, Any]:
    normalized = dict(result)
    if int(normalized.get("exitCode") or 0) == 0:
        normalized["errorCode"] = ""
        normalized.pop("errorDetails", None)
        return normalized
    existing = str(normalized.get("errorCode") or "")
    details = normalized.get("errorDetails")
    if existing and isinstance(details, dict):
        return normalized
    structured = infer_tool_error(normalized, tool)
    normalized["errorCode"] = structured["errorCode"]
    normalized["errorDetails"] = structured
    return normalized


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
    retryable = False
    if "cannot connect to the docker daemon" in lowered or "docker daemon" in lowered:
        code = ErrorCode.DOCKER_DAEMON_UNAVAILABLE
        retryable = True
    elif "timed out" in lowered or "timeout" in lowered:
        code = ErrorCode.COMMAND_TIMEOUT
        retryable = True
    elif "forbidden" in lowered or failed_step == "rbac-preflight":
        code = ErrorCode.RBAC_FORBIDDEN
    elif "insufficient nvidia.com/gpu" in lowered:
        code = ErrorCode.GPU_INSUFFICIENT
    elif "imagepull" in lowered or "image pull" in lowered:
        code = ErrorCode.IMAGE_PULL_FAILED
        retryable = True
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
        retryable = True
    resource, verb = extract_rbac_subject(text)
    return {
        "errorCode": code.value,
        "category": error_category(code),
        "message": concise_message(text, code.value),
        "stage": failed_step or tool,
        "resource": resource,
        "verb": verb,
        "retryable": retryable,
    }


def classification_for_error_code(value: Any) -> str:
    return ERROR_CLASSIFICATIONS.get(str(value or ""), "")


def error_category(code: ErrorCode) -> str:
    if code in {
        ErrorCode.RBAC_FORBIDDEN,
        ErrorCode.PATH_POLICY_VIOLATION,
        ErrorCode.VALIDATION_TARGET_DENIED,
        ErrorCode.TOOL_VALIDATION_REJECTED,
    }:
        return "policy"
    if code in {
        ErrorCode.DOCKER_DAEMON_UNAVAILABLE,
        ErrorCode.KIND_CONNECTION_FAILED,
        ErrorCode.COMMAND_TIMEOUT,
    }:
        return "infrastructure"
    if code in {
        ErrorCode.KUBERNETES_RESOURCE_NOT_FOUND,
        ErrorCode.PVC_NOT_FOUND,
        ErrorCode.GPU_INSUFFICIENT,
        ErrorCode.IMAGE_PULL_FAILED,
    }:
        return "kubernetes"
    if code in {
        ErrorCode.REQUIRED_INPUT_MISSING,
        ErrorCode.INVALID_FIELD_TYPE,
        ErrorCode.CAPABILITY_UNSUPPORTED,
    }:
        return "contract"
    return "execution"


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
