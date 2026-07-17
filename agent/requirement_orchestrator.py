"""Requirement planning, Tool execution, evaluation, and recovery workflow."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from agent import report_renderer
from agent.context_builder import (
    build_requirement_context,
    clarifying_questions,
    extract_tool_call_plan,
)
from agent.contracts import ClarificationContext
from agent.error_registry import ErrorCode, get_error_definition
from agent.evidence_builder import (
    build_requirement_evidence_trace,
    build_requirement_safety_evaluation,
)
from agent.execution_engine import execute_planned_tools
from agent.failure_context import (
    detect_failure_context,
    planner_failure_context,
)
from agent.final_evaluator import evaluate_final_result
from agent.llm.client import LLMUnavailable, config_from_env
from agent.llm.planner import LLMOutputParseError, plan_requirement_with_llm
from agent.llm_cache import (
    read_requirement_plan_cache,
    requirement_plan_cache_metadata,
    write_requirement_plan_cache,
)
from agent.orchestration_common import (
    elapsed,
    empty_final_result,
    fallback_final_result,
    finalize_timings,
    llm_result,
    make_agent_log_dir,
    raw_from_exception,
    rule_based_final_result,
    should_skip_final_llm_evaluation,
)
from agent.recovery_orchestrator import plan_recovery
from agent.report_writer import write_agent_artifacts
from agent.retrieval_context import perform_retrieval, requirement_rag_limit
from agent.summary_builder import (
    build_requirement_summary,
    collect_errors,
    collect_warnings,
)
from agent.tool_validator import validate_llm_output_schema


def run_requirement_agent(args: argparse.Namespace) -> int:
    total_started = time.perf_counter()
    requirement_path = Path(args.requirement)
    requirement_text = requirement_path.read_text(encoding="utf-8")
    # 자연어 requirement를 Agent 내부 계약으로 정규화한다.
    # 여기서 API, spec/status, 관리 리소스, 누락 정보, RAG context가 모인다.
    # 이후 단계는 원문 자연어보다 이 context를 기준으로 동작한다.
    context = build_requirement_context(
        requirement_path,
        requirement_text,
        args.workspace,
        str(getattr(args, "artifact_dir", "generated") or "generated"),
        perform_retrieval,
        requirement_rag_limit(),
    )
    context["resumeExisting"] = bool(args.resume_existing)
    context["capabilityApproval"] = {
        "proposal": str(getattr(args, "capability_proposal", "") or ""),
        "proposalId": str(getattr(args, "capability_approval", "") or ""),
    }
    log_dir = make_agent_log_dir()

    print("LLM Agent Orchestrator")
    print(f"Requirement: {context['requirement']}")
    print(
        "Primary intent: "
        f"{context['intentAnalysis'].get('primaryIntent')}"
    )
    print("Default safety mode: dry-run")
    print(f"Run level: {args.run_level}")

    if context["missingInformation"]:
        return finish_clarification_required(
            args,
            context,
            log_dir,
            total_started,
        )

    # LLM은 실행 계획만 만든다. 실제 명령 실행 여부는 아래 Tool 검증과
    # execution engine이 결정하므로, LLM 출력이 곧바로 셸 실행으로 이어지지 않는다.
    planner_started = time.perf_counter()
    planner_result = call_requirement_planner(
        args,
        requirement_text,
        context,
    )
    context["timings"]["llmPlanningSeconds"] = elapsed(planner_started)
    print_planner_cache_status(planner_result)
    if planner_result["error"]:
        return finish_planner_failure(
            args,
            context,
            planner_result,
            log_dir,
            total_started,
        )

    # 검증된 Tool만 정해진 순서로 실행한다. 실패가 발생하면 뒤 단계는
    # 실행하지 않고 failure context와 recovery planning으로 넘어간다.
    execution = execute_planned_tools(
        context,
        args.mode,
        args.execute,
        planner_result,
    )
    context["timings"].update(execution.get("timings") or {})
    initial_errors = collect_errors(execution["toolResults"])
    failure_context = detect_failure_context(
        context,
        execution,
        args.mode,
    )
    recovery_result = None
    if failure_context:
        # 복구는 자동 실행하지 않는다. 실패 근거를 저장하고,
        # 승인 가능한 복구 계획만 생성한다.
        write_recovery_checkpoint(
            log_dir,
            args,
            context,
            planner_result,
            execution,
            failure_context,
            total_started,
        )
        recovery_started = time.perf_counter()
        recovery_result = plan_recovery(
            context,
            planner_result,
            execution,
            failure_context,
            args.mode,
            extract_tool_call_plan,
            llm_result,
        )
        context["timings"]["recoveryPlanningSeconds"] = elapsed(
            recovery_started
        )
        final_result = empty_final_result(
            "Execution failed; recovery plan generated and waiting for user approval."
        )
    else:
        final_result = evaluate_or_summarize(
            args,
            context,
            planner_result,
            execution,
            initial_errors,
        )

    summary = build_requirement_summary(
        args,
        context,
        planner_result,
        execution,
        final_result,
        recovery_result,
        failure_context,
    )
    summary["timings"] = finalize_timings(
        context,
        execution,
        total_started,
    )
    summary["safetyEvaluation"] = build_requirement_safety_evaluation(
        args,
        context,
        execution,
        planner_result,
        failure_context,
    )
    summary["evidenceTrace"] = build_requirement_evidence_trace(summary)
    write_agent_artifacts(
        log_dir,
        summary,
        planner_result,
        context["retrievedKnowledge"],
        execution,
        final_result,
        recovery_result,
    )
    report = report_renderer.render_requirement_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 0 if not summary["errors"] else 1


def finish_clarification_required(
    args: argparse.Namespace,
    context: dict[str, Any],
    log_dir: Path,
    total_started: float,
) -> int:
    questions = clarifying_questions(
        context["missingInformation"],
        context["requirementSummary"],
    )
    planner_result = llm_result(
        False,
        {
            "mode": "requirement-clarification",
            "reason": "Required information is missing or ambiguous.",
        },
        {
            "requirementSummary": context["requirementSummary"].get(
                "shortSummary", ""
            ),
            "missingInformation": context["missingInformation"],
            "plannedSteps": [],
            "toolCalls": [],
            "risks": [],
            "nextActions": questions,
        },
        "",
    )
    execution = {
        "validatedToolCalls": [],
        "rejectedToolCalls": [],
        "deferredToolCalls": [],
        "toolResults": [],
        "timings": {
            "toolValidationSeconds": 0.0,
            "toolExecutionSeconds": 0.0,
        },
    }
    final_result = {
        **empty_final_result(""),
        "llmOutput": {
            "executionDecision": "clarification-required",
            "completedSteps": [],
            "failedSteps": [],
            "generatedArtifacts": [],
            "validationResults": {},
            "evidence": [
                "No Tool was executed because required information is incomplete."
            ],
            "warnings": [],
            "recommendedNextActions": questions,
            "beginnerSummary": (
                "코드를 생성하기 전에 몇 가지 정보를 확인해야 합니다."
            ),
        },
    }
    context["timings"].update(execution["timings"])
    summary = build_requirement_summary(
        args,
        context,
        planner_result,
        execution,
        final_result,
    )
    summary["runStatus"] = "clarification-required"
    summary["generatedFiles"] = {}
    clarification_code = (
        ErrorCode.INVALID_FIELD_TYPE
        if any(
            str(item).startswith("field type:")
            for item in context["missingInformation"]
        )
        else ErrorCode.REQUIRED_INPUT_MISSING
    )
    clarification_contract = get_error_definition(clarification_code)
    summary["clarificationContext"] = ClarificationContext(
        errorCode=clarification_code.value,
        category=clarification_contract.category,
        userMessage=clarification_contract.userMessage,
        recoveryPolicy=clarification_contract.recoveryPolicy,
        uiSeverity=clarification_contract.uiSeverity,
        retryable=clarification_contract.retryable,
        missingInformation=[
            str(item) for item in context["missingInformation"]
        ],
    ).to_dict()
    summary["timings"] = finalize_timings(
        context,
        execution,
        total_started,
    )
    summary["safetyEvaluation"] = build_requirement_safety_evaluation(
        args,
        context,
        execution,
        planner_result,
        None,
    )
    summary["evidenceTrace"] = build_requirement_evidence_trace(summary)
    write_agent_artifacts(
        log_dir,
        summary,
        planner_result,
        context["retrievedKnowledge"],
        execution,
        final_result,
    )
    report = report_renderer.render_requirement_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 0


def finish_planner_failure(
    args: argparse.Namespace,
    context: dict[str, Any],
    planner_result: dict[str, Any],
    log_dir: Path,
    total_started: float,
) -> int:
    execution = {
        "validatedToolCalls": [],
        "rejectedToolCalls": [],
        "deferredToolCalls": [],
        "toolResults": [],
    }
    final_result = empty_final_result(planner_result["error"])
    failure_context = planner_failure_context(
        context,
        str(planner_result["error"]),
        args.mode,
    )
    summary = build_requirement_summary(
        args,
        context,
        planner_result,
        execution,
        final_result,
        failure_context=failure_context,
    )
    summary["timings"] = finalize_timings(
        context,
        execution,
        total_started,
    )
    summary["safetyEvaluation"] = build_requirement_safety_evaluation(
        args,
        context,
        execution,
        planner_result,
        None,
    )
    summary["evidenceTrace"] = build_requirement_evidence_trace(summary)
    write_agent_artifacts(
        log_dir,
        summary,
        planner_result,
        context["retrievedKnowledge"],
        execution,
        final_result,
    )
    report = report_renderer.render_requirement_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 2


def evaluate_or_summarize(
    args: argparse.Namespace,
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, Any],
    initial_errors: list[str],
) -> dict[str, Any]:
    warnings = collect_warnings(execution["toolResults"], context)
    if should_skip_final_llm_evaluation(args):
        context["timings"]["finalLlmEvaluationSeconds"] = 0.0
        return rule_based_final_result(
            context,
            execution,
            warnings,
            initial_errors,
            args,
        )
    final_started = time.perf_counter()
    final_result = evaluate_final_result(
        context,
        planner_result,
        execution,
        warnings,
        initial_errors,
        llm_result,
    )
    context["timings"]["finalLlmEvaluationSeconds"] = elapsed(final_started)
    if final_result.get("error"):
        return fallback_final_result(
            context,
            execution,
            warnings,
            initial_errors,
            args,
            final_result,
        )
    return final_result


def write_recovery_checkpoint(
    log_dir: Path,
    args: argparse.Namespace,
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
    failure_context: dict[str, Any],
    total_started: float,
) -> None:
    pending_final = empty_final_result("Recovery planning is in progress.")
    summary = build_requirement_summary(
        args,
        context,
        planner_result,
        execution,
        pending_final,
        None,
        failure_context,
    )
    summary["runStatus"] = "recovery-planning"
    summary["timings"] = finalize_timings(
        context,
        execution,
        total_started,
    )
    summary["safetyEvaluation"] = build_requirement_safety_evaluation(
        args,
        context,
        execution,
        planner_result,
        failure_context,
    )
    summary["evidenceTrace"] = build_requirement_evidence_trace(summary)
    write_agent_artifacts(
        log_dir,
        summary,
        planner_result,
        context["retrievedKnowledge"],
        execution,
        pending_final,
    )
    (log_dir / "agent-report.md").write_text(
        report_renderer.render_requirement_report(summary),
        encoding="utf-8",
    )


def call_requirement_planner(
    args: argparse.Namespace,
    requirement_text: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    llm_input = {
        "mode": "requirement-planning",
        "requirementText": requirement_text,
        "retrievedDocs": context["retrievedKnowledge"],
        "intentAnalysis": context["intentAnalysis"],
        "workflowOptions": {
            "resumeExisting": bool(args.resume_existing),
        },
        "safetyMode": args.mode,
    }
    cache = requirement_plan_cache_metadata(llm_input)
    if (
        not args.no_cache
        and not args.refresh_cache
        and cache["path"].is_file()
    ):
        try:
            cached = read_requirement_plan_cache(cache, llm_input)
            if not cached:
                raise OSError("cache entry disappeared")
            result = llm_result(
                True,
                cached["llmInput"],
                reconcile_plan_with_context(
                    cached["llmOutput"],
                    context,
                ),
                cached["rawOutput"],
                config=config_from_env(purpose="planning"),
            )
            result["cache"] = {
                "enabled": True,
                "hit": True,
                "key": cache["key"],
                "path": str(cache["path"]),
                "createdAt": cached["createdAt"],
                "contractDigest": cache["contractDigest"],
            }
            return result
        except (OSError, json.JSONDecodeError) as exc:
            print(f"LLM plan cache read failed; refreshing cache: {exc}")
    try:
        output, exact_input, raw = plan_requirement_with_llm(
            requirement_text,
            context["retrievedKnowledge"],
            args.mode,
            context["intentAnalysis"],
            {
                "resumeExisting": bool(args.resume_existing),
            },
        )
        validate_llm_output_schema("requirement-planning", output, raw)
        output = reconcile_plan_with_context(output, context)
        result = llm_result(True, exact_input, output, raw)
        result["cache"] = {
            "enabled": not args.no_cache,
            "hit": False,
            "key": cache["key"],
            "path": str(cache["path"]),
            "refreshed": bool(args.refresh_cache),
            "contractDigest": cache["contractDigest"],
        }
        if not args.no_cache:
            write_requirement_plan_cache(
                cache["path"],
                exact_input,
                output,
                raw,
                result.get("localLLM") or {},
            )
        return result
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM planner failed."
        print(f"LLM planner failed: {message}")
        result = llm_result(
            False,
            llm_input,
            {},
            raw_from_exception(exc),
            message,
        )
        result["cache"] = {
            "enabled": not args.no_cache,
            "hit": False,
            "key": cache["key"],
            "path": str(cache["path"]),
        }
        return result


def reconcile_plan_with_context(
    output: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(output)
    missing = list(context.get("missingInformation") or [])
    normalized["missingInformation"] = missing
    if missing:
        return normalized
    normalized["risks"] = [
        item
        for item in normalized.get("risks") or []
        if "missing" not in str(item).lower()
        and "누락" not in str(item)
    ]
    normalized["nextActions"] = [
        "생성된 파일과 검증된 실행 근거를 확인합니다."
    ]
    return normalized


def print_planner_cache_status(planner_result: dict[str, Any]) -> None:
    cache = planner_result.get("cache") or {}
    if cache:
        status = "hit" if cache.get("hit") else "miss"
        print(f"Planner cache: {status} ({cache.get('path')})")
