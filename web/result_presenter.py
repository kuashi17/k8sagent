"""Translate raw Agent artifacts into a beginner-facing result."""

from __future__ import annotations

from typing import Any

from web.schemas import RunResultView


def present_run_result(job: dict[str, Any]) -> RunResultView:
    summary = job.get("summary") or {}
    requirement = summary.get("requirementSummary") or {}
    final = (summary.get("finalLLM") or {}).get("output") or {}
    errors = strings(summary.get("errors"))
    warnings = strings(summary.get("warnings"))
    tool_results = summary.get("toolResults") or []
    completed = [
        str(item.get("tool"))
        for item in tool_results
        if item.get("exitCode") == 0 and item.get("tool")
    ]
    failed = [
        str(item.get("tool"))
        for item in tool_results
        if item.get("exitCode") not in {None, 0} and item.get("tool")
    ]
    generated = [
        str(path)
        for path in (summary.get("generatedFiles") or {}).values()
        if path
    ]
    generated.extend(
        str(path)
        for path in final.get("generatedArtifacts") or []
        if path and str(path) not in generated
    )
    state = str(job.get("state") or "unknown")
    succeeded = state == "succeeded" and not errors
    kind = str(requirement.get("kind") or "")
    title = (
        f"{kind or 'Operator'} 계획이 준비됐습니다."
        if succeeded and (summary.get("agentMode") == "dry-run")
        else (
            f"{kind or 'Operator'} 작업이 완료됐습니다."
            if succeeded
            else "작업을 완료하지 못했습니다."
        )
    )
    beginner_summary = str(
        final.get("beginnerSummary")
        or requirement.get("shortSummary")
        or (
            "계획과 생성 결과를 아래에서 확인할 수 있습니다."
            if succeeded
            else "실패한 단계와 다음 조치를 확인해 주세요."
        )
    )
    return RunResultView(
        state=state,
        succeeded=succeeded,
        title=title,
        summary=beginner_summary,
        kind=kind,
        managed_resources=strings(requirement.get("managedResources")),
        completed_steps=completed,
        failed_steps=failed,
        generated_artifacts=unique(generated),
        warnings=warnings,
        errors=errors,
        next_actions=strings(summary.get("nextRecommendedActions")),
        can_execute=bool(
            succeeded
            and summary.get("agentMode") == "dry-run"
            and job.get("jobType") == "requirement"
        ),
    )


def developer_details(job: dict[str, Any]) -> dict[str, str]:
    return {
        "command": str(job.get("commandText") or ""),
        "stdout": str(job.get("stdoutTail") or ""),
        "stderr": str(job.get("stderrTail") or ""),
        "agent_log_dir": str(job.get("agentLogDir") or ""),
        "agent_report": str(job.get("agentReport") or ""),
        "summary_json": pretty(job.get("summary") or {}),
        "evidence_json": pretty(job.get("evidence") or {}),
        "safety_json": pretty(job.get("safety") or {}),
        "recovery_json": pretty(job.get("recovery") or {}),
    }


def pretty(value: dict[str, Any]) -> str:
    if not value:
        return ""
    import json

    return json.dumps(value, indent=2, ensure_ascii=False)


def strings(value: Any) -> list[str]:
    return [str(item) for item in value or [] if item]


def unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
