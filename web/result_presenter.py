"""Translate raw Agent artifacts into a beginner-facing result."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent.error_registry import get_error_definition
from agent.error_taxonomy import infer_tool_error
from agent.tools.capability_drafter import load_proposal, proposal_digest
from web.schemas import KindValidationView, LogAnalysisView, RunResultView


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
    if not result_status:
        if summary.get("runStatus") == "clarification-required":
            result_status = "clarification-required"
        elif errors:
            result_status = "failed"
        elif summary.get("agentMode") == "dry-run":
            result_status = "planned"
        else:
            result_status = "succeeded"
    failure_context = summary.get("failureContext") or {}
    error_code = str(failure_context.get("errorCode") or "")
    error_contract = get_error_definition(error_code) if error_code else None
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
    capability_support = list(
        technical.get("capabilitySupport") or []
    )
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
        error_code=error_code,
        error_message=(
            error_contract.userMessage if error_contract else ""
        ),
        error_severity=(
            error_contract.uiSeverity if error_contract else "error"
        ),
        error_retryable=(
            error_contract.retryable if error_contract else False
        ),
        next_actions=(
            beginner_strings(technical.get("nextActions"))
            or beginner_strings(summary.get("nextRecommendedActions"))
        ),
        capability_support=capability_support,
        has_experimental_capability=any(
            str(item.get("level")) == "experimental"
            for item in capability_support
            if isinstance(item, dict)
        ),
        beginner_explanation=strings(
            technical.get("beginnerExplanation")
        ),
        code_explanation=dict(technical.get("codeExplanation") or {}),
        can_execute=bool(
            (
                shared.get("canExecute")
                or (
                    shared.get("status") == "capability-awaiting-approval"
                    and not proposal_path
                )
            )
            if shared
            else (
                succeeded
                and summary.get("agentMode") == "dry-run"
                and job.get("jobType") == "requirement"
                and result_status == "planned"
            )
        ),
        capability_proposal=proposal_path,
        capability_approval=proposal_id,
        capability_resources=proposal_resources,
        capability_discovery=discovery,
        capability_discovery_errors=discovery_errors,
        needs_clarification=result_status == "clarification-required",
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


def present_kind_validation_result(
    job: dict[str, Any],
) -> KindValidationView:
    payload = job.get("kindValidation") or {}
    results = payload.get("results") or []
    result = results[0] if results else {}
    deployment = result.get("deploymentSummary") or {}
    checks = deployment.get("checks") or {}
    validator = deployment.get("validator") or {}
    runtime = (
        deployment.get("runtimeEvidence")
        or result.get("runtimeEvidence")
        or {}
    )
    succeeded = bool(
        job.get("state") == "succeeded"
        and payload.get("status") == "passed"
        and result.get("status") == "passed"
    )
    failure = infer_tool_error(
        {
            "deploymentSummary": deployment,
            "stderr": str(result.get("error") or job.get("stderrTail") or ""),
            "stdout": str(job.get("stdoutTail") or ""),
        },
        tool="kind_deployment",
    )
    error_code = "" if succeeded else str(failure.get("errorCode") or "")
    error_definition = (
        get_error_definition(error_code) if error_code else None
    )
    evidence = [
        {
            "name": name,
            "status": str((details or {}).get("status") or "unknown"),
        }
        for name, details in runtime.items()
    ]
    resources = []
    for item in checks.get("managedResources") or []:
        metadata = item.get("metadata") or {}
        resources.append(
            {
                "title": (
                    f"{item.get('kind') or 'Resource'} / "
                    f"{metadata.get('name') or ''}"
                ),
                "yaml": yaml.safe_dump(
                    item,
                    allow_unicode=True,
                    sort_keys=False,
                ),
            }
        )
    limitations = []
    for key in ("lifecycleUpdate", "immutableChange"):
        limitation = str((checks.get(key) or {}).get("limitation") or "")
        if limitation:
            limitations.append(limitation)
    compile_result = result.get("compile") or {}
    cluster_name = str(deployment.get("clusterName") or "")
    namespace = str(deployment.get("namespace") or "default")
    context = f"kind-{cluster_name}" if cluster_name else ""
    custom = validator.get("customResource") or {}
    resource_tokens = [
        f"{custom.get('resource')}/{custom.get('name')}"
    ] if custom.get("resource") and custom.get("name") else []
    resource_tokens.extend(
        f"{item.get('resource')}/{item.get('name')}"
        for item in validator.get("managedResources") or []
        if item.get("resource") and item.get("name")
    )
    command_prefix = (
        f"kubectl --context {context} -n {namespace}"
        if context
        else f"kubectl -n {namespace}"
    )
    kubectl_commands = []
    if resource_tokens:
        kubectl_commands.append(
            {
                "label": "생성된 리소스 한 번에 보기",
                "command": f"{command_prefix} get {' '.join(resource_tokens)}",
            }
        )
    kubectl_commands.extend(
        {
            "label": f"{token} 상세 YAML 보기",
            "command": f"{command_prefix} get {token} -o yaml",
        }
        for token in resource_tokens
    )
    return KindValidationView(
        succeeded=succeeded,
        title=(
            "Kubernetes 검증을 완료했습니다."
            if succeeded
            else "Kubernetes 검증을 완료하지 못했습니다."
        ),
        summary=(
            "실제 kind 클러스터에서 생성·변경·삭제 동작을 확인했습니다."
            if succeeded
            else str(
                result.get("error")
                or "실행 로그에서 실패 원인을 확인해 주세요."
            )
        ),
        kind=str(compile_result.get("kind") or ""),
        cluster_name=cluster_name,
        managed_resources=[
            f"{item.get('resource')}/{item.get('name')}"
            for item in validator.get("managedResources") or []
        ],
        observed_resources=[
            f"{item.get('resource')}/{item.get('name')}"
            for item in validator.get("observedResources") or []
        ],
        evidence=evidence,
        custom_resource_status=dict(
            checks.get("customResourceStatus") or {}
        ),
        resource_yaml=resources,
        limitations=limitations,
        kubectl_commands=kubectl_commands,
        error_code=error_code,
        error_message=(
            error_definition.userMessage if error_definition else ""
        ),
        failed_step=str(
            deployment.get("failedStep")
            or failure.get("stage")
            or ""
        ),
        retryable=bool(
            error_definition.retryable if error_definition else False
        ),
        recovery_steps=kind_recovery_steps(error_code),
    )


def kind_recovery_steps(error_code: str) -> list[str]:
    return {
        "DOCKER_DAEMON_UNAVAILABLE": [
            "Docker Desktop 또는 Docker daemon을 실행합니다.",
            "터미널에서 docker info가 성공하는지 확인합니다.",
            "환경이 준비되면 아래 다시 시도 버튼을 누릅니다.",
        ],
        "KIND_CONNECTION_FAILED": [
            "kind와 kubectl이 설치되어 있는지 확인합니다.",
            "kind get clusters와 kubectl cluster-info를 실행합니다.",
            "연결이 복구되면 아래 다시 시도 버튼을 누릅니다.",
        ],
        "COMMAND_TIMEOUT": [
            "Docker와 Kubernetes 리소스 사용량을 확인합니다.",
            "실행 중인 불필요한 kind 클러스터를 정리한 뒤 다시 시도합니다.",
        ],
    }.get(
        error_code,
        ["실패 단계와 원본 로그를 확인한 뒤 다시 시도합니다."],
    ) if error_code else []


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
