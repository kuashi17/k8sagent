"""Canonical error contracts shared by tools, recovery, and Web UI."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ErrorCode(str, Enum):
    NONE = ""
    UNKNOWN = "TOOL_EXECUTION_FAILED"
    TOOL_VALIDATION_REJECTED = "TOOL_VALIDATION_REJECTED"
    INVALID_TOOL_ARGUMENTS = "INVALID_TOOL_ARGUMENTS"
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


class ErrorDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    errorCode: ErrorCode
    category: Literal["policy", "infrastructure", "kubernetes", "contract", "execution"]
    userMessage: str
    recoveryClassification: str
    recoveryPolicy: Literal[
        "manual-review",
        "manual-correction",
        "approval-gated",
        "retry-after-environment-recovery",
    ]
    retryable: bool
    uiSeverity: Literal["info", "warning", "error", "critical"]


def definition(
    code: ErrorCode,
    category: str,
    user_message: str,
    classification: str,
    recovery_policy: str,
    retryable: bool = False,
    severity: str = "error",
) -> ErrorDefinition:
    return ErrorDefinition.model_validate(
        {
            "errorCode": code,
            "category": category,
            "userMessage": user_message,
            "recoveryClassification": classification,
            "recoveryPolicy": recovery_policy,
            "retryable": retryable,
            "uiSeverity": severity,
        }
    )


ERROR_REGISTRY = {
    item.errorCode.value: item
    for item in [
        definition(ErrorCode.UNKNOWN, "execution", "도구 실행에 실패했습니다. 원본 로그를 확인해 주세요.", "unknown", "manual-review"),
        definition(ErrorCode.TOOL_VALIDATION_REJECTED, "policy", "안전 정책에서 허용하지 않는 작업이어서 실행하지 않았습니다.", "tool-validation", "manual-correction", severity="critical"),
        definition(ErrorCode.INVALID_TOOL_ARGUMENTS, "policy", "도구 입력값이 계약과 맞지 않습니다.", "tool-validation", "manual-correction"),
        definition(ErrorCode.PATH_POLICY_VIOLATION, "policy", "허용된 작업 경로를 벗어나 실행을 차단했습니다.", "path-safety", "manual-correction", severity="critical"),
        definition(ErrorCode.REQUIRED_INPUT_MISSING, "contract", "작업에 필요한 입력이 부족합니다.", "incomplete-requirement", "manual-correction"),
        definition(ErrorCode.INVALID_FIELD_TYPE, "contract", "지원하지 않거나 불명확한 필드 타입이 있습니다.", "invalid-field-type", "approval-gated"),
        definition(ErrorCode.CAPABILITY_UNSUPPORTED, "contract", "현재 지원 계약에 없는 Kubernetes 리소스입니다.", "unsupported-capability", "manual-correction"),
        definition(ErrorCode.VALIDATION_TARGET_DENIED, "policy", "허용되지 않은 검증 명령을 차단했습니다.", "validation-target-denied", "manual-correction", severity="critical"),
        definition(ErrorCode.VALIDATION_FAILED, "execution", "생성 코드의 빌드 또는 테스트가 실패했습니다.", "go-build-test-failure", "manual-review"),
        definition(ErrorCode.ARTIFACT_MISSING, "execution", "다음 단계에 필요한 생성 파일을 찾지 못했습니다.", "missing-artifact", "manual-correction"),
        definition(ErrorCode.RBAC_FORBIDDEN, "policy", "Controller에 필요한 Kubernetes 권한이 부족합니다.", "rbac-forbidden", "approval-gated", severity="critical"),
        definition(ErrorCode.KUBERNETES_RESOURCE_NOT_FOUND, "kubernetes", "필요한 Kubernetes 리소스를 찾지 못했습니다.", "resource-not-found", "manual-correction"),
        definition(ErrorCode.PVC_NOT_FOUND, "kubernetes", "참조한 PVC를 찾지 못했습니다.", "pvc-not-found", "approval-gated"),
        definition(ErrorCode.GPU_INSUFFICIENT, "kubernetes", "클러스터에 요청한 GPU 리소스가 부족합니다.", "gpu-insufficient", "manual-correction", severity="warning"),
        definition(ErrorCode.IMAGE_PULL_FAILED, "kubernetes", "컨테이너 이미지를 가져오지 못했습니다.", "image-pull", "retry-after-environment-recovery", True),
        definition(ErrorCode.DOCKER_DAEMON_UNAVAILABLE, "infrastructure", "Docker daemon에 연결할 수 없습니다.", "docker-kind-connection", "retry-after-environment-recovery", True),
        definition(ErrorCode.KIND_CONNECTION_FAILED, "infrastructure", "kind 클러스터에 연결할 수 없습니다.", "docker-kind-connection", "retry-after-environment-recovery", True),
        definition(ErrorCode.COMMAND_TIMEOUT, "infrastructure", "명령이 제한 시간 안에 끝나지 않았습니다.", "command-timeout", "retry-after-environment-recovery", True, "warning"),
    ]
}


def get_error_definition(value: ErrorCode | str) -> ErrorDefinition:
    code = value.value if isinstance(value, ErrorCode) else str(value or "")
    return ERROR_REGISTRY.get(code, ERROR_REGISTRY[ErrorCode.UNKNOWN.value])


def validate_error_registry() -> None:
    expected = {item.value for item in ErrorCode if item is not ErrorCode.NONE}
    actual = set(ERROR_REGISTRY)
    if expected != actual:
        raise RuntimeError(
            f"Error registry mismatch: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


validate_error_registry()
