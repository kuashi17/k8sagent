"""Deterministic recovery classification and approval-gated Tool policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent.contracts import RecoveryPlan
from agent.error_taxonomy import classification_for_error_code
from agent.tool_validator import normalize_tool_name


RECOVERY_TOOL_ALLOWLIST = {
    "requirement_editor",
    "spec_generator",
    "command_planner",
    "scaffold_runner",
    "artifact_patcher",
    "validation",
    "log_analyzer",
    "kind_deployment",
}
SUPPORTED_FIELD_TYPES = {
    "string",
    "bool",
    "boolean",
    "int",
    "int32",
    "int64",
    "float32",
    "float64",
    "[]string",
    "map[string]string",
    "metav1.Time",
}


def deterministic_recovery_classification(failure_context: dict[str, Any]) -> str:
    structured = classification_for_error_code(
        failure_context.get("errorCode")
    )
    if structured:
        return structured
    failed_tool = str(failure_context.get("failedTool") or "")
    failed_step = str(failure_context.get("failedStep") or "")
    text = " ".join(
        [
            str(failure_context.get("stderrTail") or ""),
            str(failure_context.get("stdoutTail") or ""),
        ]
    ).lower()
    if failed_tool == "kind_deployment" and (
        failed_step == "docker-info"
        or "cannot connect to the docker daemon" in text
        or "docker daemon" in text
    ):
        return "docker-kind-connection"
    return ""


def scrub_failure_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key != "failedResult"}


def validate_recovery_plan(
    raw_plan: dict[str, Any],
    failure_context: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    unsupported = detect_unsupported_field_types(context)
    has_structured_error = bool(failure_context.get("errorCode"))
    classification = policy_classification(raw_plan, failure_context, unsupported)
    rejected = validate_raw_recovery_calls(raw_plan, classification)

    if classification == "invalid-field-type" and unsupported:
        field = unsupported[0]
        evidence_refs = [
            f"operatorSpec:{field['section']}.{field['name']}",
            f"failedTool:{failure_context.get('failedTool')}",
            f"failedStep:{failure_context.get('failedStep')}",
        ]
        validated_calls = invalid_field_type_recovery_calls(field, evidence_refs)
        root_cause = f"{field['name']} field uses unsupported type: {field['type']}"
        proposed = [
            f"Change {field['name']} from {field['type']} to one of: {', '.join(sorted(SUPPORTED_FIELD_TYPES))}.",
            "Regenerate the operator spec, patch artifacts, then run make generate/manifests/test.",
        ]
        rerun_from = "requirement correction"
    elif classification == "gpu-insufficient":
        validated_calls = []
        root_cause = raw_plan.get("rootCause") or "GPU resource is unavailable in the current cluster."
        proposed = [
            "Use a gpuCount 0 test sample for local kind validation.",
            "Run on a GPU-capable cluster when validating GPU scheduling.",
        ]
        rerun_from = "manual review"
    else:
        validated_calls = generic_validated_recovery_calls(classification, failure_context)
        actual_failure = (
            (failure_context.get("errorDetails") or {}).get("message")
            or failure_context.get("stderrTail")
            or failure_context.get("stdoutTail")
            or "Recovery requires manual review."
        )
        root_cause = (
            actual_failure
            if classification == "unknown" or has_structured_error
            else raw_plan.get("rootCause") or actual_failure
        )
        proposed = (
            [
                "실제 stdout/stderr와 요구사항을 확인하고 불명확한 필드 또는 설정을 수정합니다."
            ]
            if classification == "unknown"
            else raw_plan.get("proposedFixes")
            if isinstance(raw_plan.get("proposedFixes"), list)
            else ["Review failure-context.json and approve the smallest safe recovery step."]
        )
        rerun_from = str(failure_context.get("failedTool") or "failed step")

    approval_required = bool(validated_calls)
    recovery_status = (
        "waiting-for-user-approval"
        if approval_required
        else "manual-correction-required"
    )
    validated_plan = {
        "decision": "manual-review-required" if classification in {"unknown", "image-pull"} else "recovery-required",
        "classification": classification,
        "rootCause": root_cause,
        "evidence": (
            raw_plan.get("evidence")
            if classification != "unknown"
            and not has_structured_error
            and isinstance(raw_plan.get("evidence"), list)
            else default_recovery_evidence(failure_context, unsupported)
        ),
        "proposedFixes": proposed,
        "recoveryToolCalls": (
            raw_plan.get("recoveryToolCalls")
            if isinstance(raw_plan.get("recoveryToolCalls"), list)
            else []
        ),
        "validatedRecoveryToolCalls": validated_calls,
        "rejectedRecoveryToolCalls": rejected,
        "rerunFromStep": rerun_from,
        "risks": (
            raw_plan.get("risks")
            if isinstance(raw_plan.get("risks"), list)
            else ["Recovery calls require user approval before execution."]
        ),
        "beginnerSummary": raw_plan.get("beginnerSummary")
        or (
            "검증된 복구 작업이 있어 사용자 승인을 기다립니다."
            if approval_required
            else "자동 복구 근거가 부족합니다. 실제 오류와 요구사항을 확인해 직접 수정해 주세요."
        ),
        "status": recovery_status,
    }
    validated_plan = RecoveryPlan.model_validate(validated_plan).to_dict()
    return {
        "validatedRecoveryPlan": validated_plan,
        "rejectedRecoveryToolCalls": rejected,
        "policyEvaluation": {
            "classification": classification,
            "errorCode": str(failure_context.get("errorCode") or ""),
            "unsupportedFieldTypes": unsupported,
            "allowlist": sorted(RECOVERY_TOOL_ALLOWLIST),
            "rawRecoveryToolCalls": raw_plan.get("recoveryToolCalls") or [],
            "validatedRecoveryToolCalls": validated_calls,
            "rejectedRecoveryToolCalls": rejected,
            "status": recovery_status,
        },
    }


def invalid_field_type_recovery_calls(
    field: dict[str, str],
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    return [
        {
            "tool": "requirement_editor",
            "mode": "execute",
            "reason": f"Replace unsupported type {field['type']} with a supported Go type.",
            "requiresApproval": True,
            "evidenceRefs": evidence_refs,
            "expectedEffect": "The natural-language requirement no longer contains an unsupported field type.",
            "verificationStep": "Review the edited requirement before regenerating the operator spec.",
        },
        {
            "tool": "spec_generator",
            "mode": "execute",
            "reason": "Regenerate operator spec after the approved type correction.",
            "requiresApproval": True,
            "evidenceRefs": evidence_refs,
            "expectedEffect": "operator-spec.yaml contains only supported field types.",
            "verificationStep": "Inspect specFields/statusFields in the regenerated operator-spec.yaml.",
        },
        {
            "tool": "artifact_patcher",
            "mode": "execute",
            "reason": "Apply the corrected API type to generated Kubebuilder artifacts.",
            "requiresApproval": True,
            "evidenceRefs": evidence_refs,
            "expectedEffect": "Go API types compile with the corrected field type.",
            "verificationStep": "Run the validation Tool after patching.",
        },
        {
            "tool": "validation",
            "mode": "execute",
            "targets": ["make generate", "make manifests", "make test"],
            "reason": "Verify generated code, manifests, and tests after the approved correction.",
            "requiresApproval": True,
            "evidenceRefs": evidence_refs,
            "expectedEffect": "make generate, make manifests, and make test succeed.",
            "verificationStep": "Check validationResults for all succeeded.",
        },
    ]


def detect_unsupported_field_types(context: dict[str, Any]) -> list[dict[str, str]]:
    spec_path = Path(context["generatedFiles"]["operatorSpec"])
    if not spec_path.is_file():
        return []
    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(spec, dict):
        return []
    unsupported = []
    for section_name, key in (("specFields", "specFields"), ("statusFields", "statusFields")):
        for field in spec.get(key) or []:
            if not isinstance(field, dict):
                continue
            field_type = str(field.get("type") or "")
            if field_type and field_type not in SUPPORTED_FIELD_TYPES:
                unsupported.append({"section": section_name, "name": str(field.get("name") or ""), "type": field_type})
    return unsupported


def policy_classification(
    raw_plan: dict[str, Any],
    failure_context: dict[str, Any],
    unsupported: list[dict[str, str]],
) -> str:
    structured = classification_for_error_code(
        failure_context.get("errorCode")
    )
    if structured:
        return structured
    if unsupported:
        return "invalid-field-type"
    text = " ".join(
        [
            str(raw_plan.get("classification") or ""),
            str(raw_plan.get("rootCause") or ""),
            str(failure_context.get("stderrTail") or ""),
            str(failure_context.get("stdoutTail") or ""),
        ]
    ).lower()
    if "forbidden" in text or "rbac" in text:
        return "rbac-forbidden"
    if "pvc" in text and "not found" in text:
        return "pvc-not-found"
    if "gpu" in text or "nvidia.com/gpu" in text:
        return "gpu-insufficient"
    if "imagepull" in text or "image pull" in text:
        return "image-pull"
    if (
        "cannot connect to the docker daemon" in text
        or "docker daemon" in text
        or ("kind" in text and "connection" in text)
    ):
        return "docker-kind-connection"
    return "unknown"


def validate_raw_recovery_calls(raw_plan: dict[str, Any], classification: str) -> list[dict[str, str]]:
    rejected = []
    raw_calls = raw_plan.get("recoveryToolCalls") or []
    if not isinstance(raw_calls, list):
        return rejected
    for item in raw_calls:
        if not isinstance(item, dict):
            rejected.append({"tool": "unknown", "reason": "Recovery Tool call is not an object."})
            continue
        tool = str(item.get("tool") or "")
        if normalize_tool_name(tool) not in RECOVERY_TOOL_ALLOWLIST:
            rejected.append({"tool": tool, "reason": rejected_recovery_reason(tool, classification)})
    return rejected


def rejected_recovery_reason(tool: str, classification: str) -> str:
    if tool == "controller-gen" and classification == "invalid-field-type":
        return "Not in recovery allowlist and rerunning alone does not correct the invalid field type."
    if tool == "go_version_checker" and classification == "invalid-field-type":
        return "No evidence that the Go version caused this failure."
    return "Not in recovery allowlist."


def generic_validated_recovery_calls(
    classification: str,
    failure_context: dict[str, Any],
) -> list[dict[str, Any]]:
    evidence_refs = [
        f"failedTool:{failure_context.get('failedTool')}",
        f"failedStep:{failure_context.get('failedStep')}",
    ]
    if classification == "rbac-forbidden":
        return [
            {
                "tool": "artifact_patcher",
                "mode": "execute",
                "reason": "Update RBAC markers and manifests after user approval.",
                "requiresApproval": True,
                "evidenceRefs": evidence_refs,
                "expectedEffect": "RBAC resources and verbs match controller needs.",
                "verificationStep": "Run validation with make manifests and make test.",
            },
            {
                "tool": "validation",
                "mode": "execute",
                "targets": ["make manifests", "make test"],
                "reason": "Verify RBAC manifests and tests after patching.",
                "requiresApproval": True,
                "evidenceRefs": evidence_refs,
                "expectedEffect": "RBAC manifests regenerate and tests pass.",
                "verificationStep": "Check validationResults.",
            },
        ]
    if classification == "pvc-not-found":
        return [
            {
                "tool": "validation",
                "mode": "dry-run",
                "reason": "Re-run validation after the sample or PVC reference is corrected by the user.",
                "requiresApproval": True,
                "evidenceRefs": evidence_refs,
                "expectedEffect": "PVC reference is valid for the target environment.",
                "verificationStep": "Run e2e manually after approval.",
            }
        ]
    if classification == "docker-kind-connection":
        return [
            {
                "tool": "kind_deployment",
                "mode": "execute",
                "reason": "Re-run only the kind deployment stage after Docker connectivity is restored.",
                "requiresApproval": True,
                "evidenceRefs": evidence_refs,
                "expectedEffect": "Docker and kind commands can connect and the deployment verification resumes.",
                "verificationStep": "Run docker info and kind get clusters, then approve kind_deployment.",
            }
        ]
    return []


def default_recovery_evidence(
    failure_context: dict[str, Any],
    unsupported: list[dict[str, str]],
) -> list[str]:
    evidence = []
    if unsupported:
        evidence.extend(f"{item['section']}.{item['name']} type={item['type']}" for item in unsupported)
    if failure_context.get("failedTool"):
        evidence.append(f"failedTool={failure_context.get('failedTool')}")
    if failure_context.get("failedStep"):
        evidence.append(f"failedStep={failure_context.get('failedStep')}")
    if failure_context.get("exitCode") is not None:
        evidence.append(f"exitCode={failure_context.get('exitCode')}")
    if failure_context.get("errorCode"):
        evidence.append(f"errorCode={failure_context.get('errorCode')}")
    details = failure_context.get("errorDetails") or {}
    if details.get("resource"):
        evidence.append(f"resource={details.get('resource')}")
    if details.get("verb"):
        evidence.append(f"verb={details.get('verb')}")
    return evidence
