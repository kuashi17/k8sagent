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
    extract_tool_call_plan,
)
from agent.evidence_builder import (
    build_requirement_evidence_trace,
    build_requirement_safety_evaluation,
)
from agent.execution_engine import execute_planned_tools
from agent.failure_context import detect_failure_context
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
    load_profile,
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
from agent.tool_validator import (
    normalize_tool_name,
    validate_llm_output_schema,
)


def run_requirement_agent(args: argparse.Namespace) -> int:
    total_started = time.perf_counter()
    requirement_path = Path(args.requirement)
    requirement_text = requirement_path.read_text(encoding="utf-8")
    profile = load_profile(Path(args.profile)) if args.profile else {}
    context = build_requirement_context(
        requirement_path,
        requirement_text,
        args.profile,
        profile,
        args.workspace,
        perform_retrieval,
        requirement_rag_limit(),
    )
    context["kindDeploymentRequested"] = bool(args.kind_deploy)
    context["resumeExisting"] = bool(args.resume_existing)
    log_dir = make_agent_log_dir()

    print("LLM Agent Orchestrator")
    print(f"Requirement: {context['requirement']}")
    print(
        "Profile hint: "
        f"{context['selectedProfile'].get('path') or '<none>'}"
    )
    print(
        "Primary intent: "
        f"{context['intentAnalysis'].get('primaryIntent')}"
    )
    print("Default safety mode: dry-run")
    print(f"Run level: {args.run_level}")

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

    if args.kind_deploy:
        ensure_requested_tool_call(
            planner_result,
            "validation",
            args.mode,
            (
                "kind deployment requires make generate, make manifests, "
                "and make test to pass first."
            ),
        )
        ensure_requested_tool_call(
            planner_result,
            "kind_deployment",
            args.mode,
            (
                "User explicitly requested profile-backed kind deployment "
                "after validation."
            ),
        )
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
    summary = build_requirement_summary(
        args,
        context,
        planner_result,
        execution,
        final_result,
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
        "profileSummary": context["selectedProfile"],
        "intentAnalysis": context["intentAnalysis"],
        "profileCandidates": context["profileCandidates"],
        "workflowOptions": {
            "kindDeploymentRequested": bool(args.kind_deploy),
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
            }
            return result
        except (OSError, json.JSONDecodeError) as exc:
            print(f"LLM plan cache read failed; refreshing cache: {exc}")
    try:
        output, exact_input, raw = plan_requirement_with_llm(
            requirement_text,
            context["retrievedKnowledge"],
            context["selectedProfile"],
            args.mode,
            context["intentAnalysis"],
            context["profileCandidates"],
            {
                "kindDeploymentRequested": bool(args.kind_deploy),
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
        "Review generated artifacts and validated Tool evidence."
    ]
    return normalized


def print_planner_cache_status(planner_result: dict[str, Any]) -> None:
    cache = planner_result.get("cache") or {}
    if cache:
        status = "hit" if cache.get("hit") else "miss"
        print(f"Planner cache: {status} ({cache.get('path')})")


def ensure_requested_tool_call(
    planner_result: dict[str, Any],
    tool: str,
    agent_mode: str,
    reason: str,
) -> None:
    output = planner_result.get("llmOutput")
    if not isinstance(output, dict):
        return
    calls = output.setdefault("toolCalls", [])
    if not isinstance(calls, list):
        return
    if any(
        isinstance(item, dict)
        and normalize_tool_name(str(item.get("tool") or "")) == tool
        for item in calls
    ):
        return
    calls.append(
        {
            "tool": tool,
            "mode": (
                "execute" if agent_mode == "execute" else "dry-run"
            ),
            "reason": reason,
            "source": "explicit-user-workflow-option",
        }
    )
