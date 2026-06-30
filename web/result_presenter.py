"""Translate raw Agent artifacts into a beginner-facing result."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.capability_drafter import load_proposal, proposal_digest
from web.schemas import LogAnalysisView, RunResultView


REPO_ROOT = Path(__file__).resolve().parents[1]

BEGINNER_TEXT = {
    "Review validated Tool calls and generated artifacts.": (
        "생성 계획과 안전 검사 결과를 확인합니다."
    ),
    "Use execute mode only after reviewing safety-evaluation.json.": (
        "문제가 없으면 화면에서 실제 생성을 승인해 코드 생성과 검증을 진행합니다."
    ),
    "Review generated artifacts and validated Tool evidence.": (
        "생성된 파일과 검증된 실행 근거를 확인합니다."
    ),
    "A deterministic summary was built from validated Tool exit codes.": (
        "검증된 작업 결과를 바탕으로 실행 요약을 만들었습니다."
    ),
    "Final LLM evaluation skipped by fast mode.": (
        "빠른 계획 모드에서는 최종 LLM 평가를 생략했습니다."
    ),
}


def present_run_result(job: dict[str, Any]) -> RunResultView:
    summary = job.get("summary") or {}
    shared = summary.get("agentResult") or {}
    technical = shared.get("technicalDetails") or {}
    requirement = summary.get("requirementSummary") or {}
    final = (summary.get("finalLLM") or {}).get("output") or {}
    errors = strings(technical.get("errors") or summary.get("errors"))
    warnings = beginner_strings(
        technical.get("warnings") or summary.get("warnings")
    )
    tool_results = summary.get("toolResults") or []
    completed = strings(technical.get("completedSteps")) or [
        tool_label(str(item.get("tool")))
        for item in tool_results
        if item.get("exitCode") == 0 and item.get("tool")
    ]
    failed = strings(technical.get("failedSteps")) or [
        tool_label(str(item.get("tool")))
        for item in tool_results
        if item.get("exitCode") not in {None, 0} and item.get("tool")
    ]
    generated = strings(technical.get("generatedArtifacts")) or [
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
    kind = str(technical.get("kind") or requirement.get("kind") or "")
    (
        proposal_path,
        proposal_id,
        proposal_resources,
        discovery,
        discovery_errors,
    ) = capability_review(summary)
    result_status = str(shared.get("status") or "")
    title = (
        "추가 정보가 필요합니다."
        if result_status == "clarification-required"
        else f"{kind or 'Operator'} 계획이 준비됐습니다."
        if succeeded and (summary.get("agentMode") == "dry-run")
        else (
            f"{kind or 'Operator'} 작업이 완료됐습니다."
            if succeeded
            else "작업을 완료하지 못했습니다."
        )
    )
    beginner_summary = beginner_text(str(
        shared.get("beginnerSummary")
        or final.get("beginnerSummary")
        or requirement.get("shortSummary")
        or (
            "계획과 생성 결과를 아래에서 확인할 수 있습니다."
            if succeeded
            else "실패한 단계와 다음 조치를 확인해 주세요."
        )
    ))
    return RunResultView(
        state=state,
        succeeded=succeeded,
        title=title,
        summary=beginner_summary,
        kind=kind,
        managed_resources=(
            strings(technical.get("managedResources"))
            or strings(requirement.get("managedResources"))
        ),
        observed_resources=(
            strings(technical.get("observedResources"))
            or strings(requirement.get("observedResources"))
        ),
        completed_steps=completed,
        failed_steps=failed,
        generated_artifacts=unique(generated),
        warnings=warnings,
        errors=errors,
        next_actions=(
            beginner_strings(technical.get("nextActions"))
            or beginner_strings(summary.get("nextRecommendedActions"))
        ),
        capability_support=list(technical.get("capabilitySupport") or []),
        beginner_explanation=strings(
            technical.get("beginnerExplanation")
        ),
        code_explanation=dict(technical.get("codeExplanation") or {}),
        can_execute=bool(
            shared.get("canExecute")
            if shared
            else (
                succeeded
                and summary.get("agentMode") == "dry-run"
                and job.get("jobType") == "requirement"
            )
        ),
        capability_proposal=proposal_path,
        capability_approval=proposal_id,
        capability_resources=proposal_resources,
        capability_discovery=discovery,
        capability_discovery_errors=discovery_errors,
    )


def present_log_analysis_result(job: dict[str, Any]) -> LogAnalysisView:
    summary = job.get("summary") or {}
    analysis = summary.get("llmAnalysis") or {}
    errors = strings(summary.get("errors"))
    analyzer = summary.get("logAnalyzerResult") or {}
    succeeded = (
        job.get("state") == "succeeded"
        and analyzer.get("exitCode") == 0
        and not errors
    )
    fallback_used = not bool(summary.get("llmPlannerUsed"))
    return LogAnalysisView(
        succeeded=succeeded,
        title=(
            "로그 분석이 완료됐습니다."
            if succeeded
            else "로그 분석을 완료하지 못했습니다."
        ),
        summary=str(
            analysis.get("explanationForBeginner")
            or (
                "로그에서 확인된 원인과 다음 조치를 정리했습니다."
                if succeeded
                else "분석 도구의 오류를 확인해 주세요."
            )
        ),
        source_log_dir=str(summary.get("sourceLogDir") or ""),
        classification=str(
            analysis.get("classification") or "unknown"
        ),
        root_cause=str(
            analysis.get("rootCause")
            or "확정된 원인이 없습니다."
        ),
        evidence=strings(analysis.get("evidence")),
        recommended_fixes=strings(analysis.get("recommendedFixes")),
        warnings=strings(summary.get("warnings")),
        errors=errors,
        deterministic=fallback_used,
    )


def beginner_text(value: str) -> str:
    return BEGINNER_TEXT.get(value, value)


def beginner_strings(value: Any) -> list[str]:
    return [beginner_text(item) for item in strings(value)]


def capability_review(
    summary: dict[str, Any],
) -> tuple[str, str, list[str], list[str], list[str]]:
    relative = str(
        (summary.get("generatedFiles") or {}).get(
            "capabilityProposal"
        )
        or ""
    )
    if not relative:
        return "", "", [], [], []
    path = (REPO_ROOT / relative).resolve()
    try:
        path.relative_to((REPO_ROOT / "generated").resolve())
    except ValueError:
        return "", "", [], [], []
    if not path.is_file():
        return "", "", [], [], []
    try:
        proposal = load_proposal(path)
    except (OSError, ValueError):
        return "", "", [], [], []
    if (
        proposal.status != "pending-approval"
        or proposal.approved
        or proposal.proposalId != proposal_digest(proposal)
    ):
        return "", "", [], [], []
    resources = [
        f"{item.kind} · {item.apiVersion} · {item.scope.value.lower()}"
        for item in proposal.capabilities
    ]
    discovery = [
        (
            f"{item.kind} · resource={item.resource} · "
            f"scope={item.scope} · RBAC="
            f"{item.rbacApiGroup or 'core'}/{item.rbacResource} "
            f"[{','.join(item.rbacVerbs)}]"
        )
        for item in proposal.discoveryValidation
    ]
    return (
        relative,
        proposal.proposalId,
        resources,
        discovery,
        list(proposal.discoveryErrors),
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


def tool_label(value: str) -> str:
    return {
        "spec_generator": "요구사항 구조화",
        "capability_drafter": "관리 리소스 지원 확인",
        "command_planner": "안전한 작업 계획",
        "scaffold_runner": "프로젝트 뼈대 생성",
        "artifact_patcher": "Controller 코드 생성",
        "validation": "코드 및 테스트 검증",
        "kind_deployment": "로컬 클러스터 검증",
    }.get(value, value.replace("_", " "))
