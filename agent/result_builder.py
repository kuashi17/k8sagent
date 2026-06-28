"""Build the shared Agent/Web result contract from an Agent summary."""

from __future__ import annotations

from typing import Any

from agent.contracts import AgentResult
from agent.capability_support import support_for


def build_agent_result(summary: dict[str, Any]) -> dict[str, Any]:
    final = (summary.get("finalLLM") or {}).get("output") or {}
    requirement = summary.get("requirementSummary") or {}
    errors = strings(summary.get("errors"))
    warnings = strings(summary.get("warnings"))
    tool_results = summary.get("toolResults") or []
    managed_resources = strings(requirement.get("managedResources"))
    capability_support = support_for(managed_resources)
    generated = unique(
        [
            str(path)
            for path in (summary.get("generatedFiles") or {}).values()
            if path
        ]
        + strings(final.get("generatedArtifacts"))
    )
    recovery = summary.get("recovery") or {}
    proposal_path = str(
        (summary.get("generatedFiles") or {}).get("capabilityProposal")
        or ""
    )
    approvals = []
    if proposal_path:
        approvals.append(
            {
                "type": "capability",
                "reason": "A new managed-resource capability requires explicit review.",
                "proposalPath": proposal_path,
            }
        )
    if recovery.get("waitingForUserApproval"):
        approvals.append(
            {
                "type": "recovery",
                "reason": "Recovery actions are never executed without user approval.",
            }
        )

    status = result_status(summary, errors, approvals)
    result = AgentResult.model_validate(
        {
            "status": status,
            "succeeded": not errors and status != "failed",
            "beginnerSummary": str(
                final.get("beginnerSummary")
                or requirement.get("shortSummary")
                or default_summary(status)
            ),
            "technicalDetails": {
                "kind": str(requirement.get("kind") or ""),
                "managedResources": managed_resources,
                "completedSteps": [
                    str(item.get("tool"))
                    for item in tool_results
                    if item.get("exitCode") == 0 and item.get("tool")
                ],
                "failedSteps": [
                    str(item.get("tool"))
                    for item in tool_results
                    if item.get("exitCode") not in {None, 0}
                    and item.get("tool")
                ],
                "generatedArtifacts": generated,
                "warnings": warnings,
                "errors": errors,
                "nextActions": strings(
                    summary.get("nextRecommendedActions")
                ),
                "capabilitySupport": capability_support,
                "beginnerExplanation": beginner_explanation(
                    str(requirement.get("kind") or ""),
                    capability_support,
                    final.get("validationResults") or {},
                ),
            },
            "approvalRequests": approvals,
            "validationResults": final.get("validationResults") or {},
            "recoveryState": recovery,
            "canExecute": bool(
                not errors
                and summary.get("agentMode") == "dry-run"
                and not approvals
            ),
        }
    )
    return result.to_dict()


def result_status(
    summary: dict[str, Any],
    errors: list[str],
    approvals: list[dict[str, Any]],
) -> str:
    if errors:
        return "failed"
    if summary.get("runStatus") == "recovery-planning":
        return "recovery-planning"
    if any(item["type"] == "recovery" for item in approvals):
        return "recovery-awaiting-approval"
    if any(item["type"] == "capability" for item in approvals):
        return "capability-awaiting-approval"
    if summary.get("agentMode") == "dry-run":
        return "planned"
    return "succeeded"


def default_summary(status: str) -> str:
    if status == "failed":
        return "실패한 단계와 다음 조치를 확인해 주세요."
    if "approval" in status or status == "recovery-planning":
        return "안전한 다음 작업을 위해 사용자 승인이 필요합니다."
    return "계획과 생성 결과를 확인할 수 있습니다."


def strings(value: Any) -> list[str]:
    return [str(item) for item in value or [] if item]


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def beginner_explanation(
    kind: str,
    support: list[dict[str, Any]],
    validation: dict[str, Any],
) -> list[str]:
    lines = [
        f"{kind or 'Custom Resource'} 변경을 감지하는 Controller를 구성했습니다."
    ]
    lines.extend(
        f"{item['resource']} 관리 기능은 {item['level']} 단계입니다. {item['explanation']}"
        for item in support
    )
    passed = [
        name for name, status in validation.items() if status == "succeeded"
    ]
    if passed:
        lines.append("자동 검증 완료: " + ", ".join(passed))
    lines.append("실제 실행 전 생성 파일과 권한 범위를 검토할 수 있습니다.")
    return lines
