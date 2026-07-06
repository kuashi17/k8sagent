"""Canonical user-visible workflow states for Web jobs."""

from __future__ import annotations

from typing import Any, Literal


WorkflowState = Literal[
    "clarification-required",
    "planned",
    "approved",
    "generating",
    "generated",
    "kind-validating",
    "kind-failed",
    "kind-passed",
    "log-analysis",
    "recovery-proposed",
    "execution-failed",
]


GENERATION_PHASES = {
    "spec generation",
    "command planning",
    "scaffold",
    "artifact patch",
    "validation",
}


def workflow_state(job: dict[str, Any]) -> WorkflowState:
    """Resolve storage/process fields into one unambiguous UI state."""
    job_type = str(job.get("jobType") or "requirement")
    state = str(job.get("state") or "queued")
    phase = str(job.get("phase") or "queued")
    summary = job.get("summary") or {}

    if job_type == "log-analysis":
        return "log-analysis"
    if job_type == "kind-validation":
        if state not in {"succeeded", "failed", "canceled", "interrupted"}:
            return "kind-validating"
        payload = job.get("kindValidation") or {}
        results = payload.get("results") or []
        passed = bool(
            state == "succeeded"
            and payload.get("status") == "passed"
            and results
            and all(item.get("status") == "passed" for item in results)
        )
        return "kind-passed" if passed else "kind-failed"

    if summary.get("runStatus") == "clarification-required":
        return "clarification-required"
    recovery = summary.get("recovery") or job.get("recovery") or {}
    if recovery.get("plan") or recovery.get("waitingForUserApproval"):
        return "recovery-proposed"
    if state in {"failed", "canceled", "interrupted"}:
        return "execution-failed"
    if state == "succeeded":
        return "planned" if summary.get("agentMode") == "dry-run" else "generated"
    if phase in GENERATION_PHASES:
        return "generating"
    if (job.get("metadata") or {}).get("approvalParentJobId"):
        return "approved"
    return "generating" if state == "running" else "approved"
