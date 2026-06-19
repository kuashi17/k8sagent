#!/usr/bin/env python3
"""LLM-based Agent orchestrator for the Kubebuilder automation MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llm.client import LLMUnavailable, config_from_env  # noqa: E402
from agent.execution_engine import execute_planned_tools, order_validated_tool_calls  # noqa: E402
from agent.llm.planner import (  # noqa: E402
    LLMOutputParseError,
    analyze_log_with_llm,
    evaluate_tool_results_with_llm,
    plan_recovery_with_llm,
    plan_requirement_with_llm,
)
from agent.rag.retriever import search_detailed as retrieve_knowledge_detailed  # noqa: E402
from agent.recovery_policy import (  # noqa: E402
    deterministic_recovery_classification,
    scrub_failure_context,
    validate_recovery_plan,
)
from agent.report_writer import write_agent_artifacts, write_tool_output_logs  # noqa: E402
from agent.requirement_analyzer import analyze_requirement_intent, select_profile_hint  # noqa: E402
from agent.tool_validator import (  # noqa: E402
    is_inside_repo,
    normalize_tool_name,
    planned_tool_calls,
    validate_llm_output_schema,
    validate_planned_tool_calls,
)
from agent.tools import langchain_wrappers as tools  # noqa: E402


AGENT_CACHE_ROOT = Path(".cache") / "agent"
REQUIREMENT_PLAN_CACHE_VERSION = "requirement-planning-v4"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LLM-based Kubebuilder Agent orchestrator.")
    parser.add_argument("--requirement", help="Natural language requirement file.")
    parser.add_argument("--log-dir", help="Existing logs/scaffold, logs/patch, or logs/e2e directory to analyze.")
    parser.add_argument("--analyze-log", help="Alias of --log-dir.")
    parser.add_argument("--profile", help="Profile YAML path.")
    parser.add_argument("--planner", default="llm", choices=["llm"], help="Only the LLM planner is supported.")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "execute"], help="Agent mode. Defaults to dry-run.")
    parser.add_argument(
        "--run-level",
        default="fast",
        choices=["fast", "standard", "full"],
        help="Execution depth. fast is the default and skips final LLM evaluation; standard adds final LLM evaluation; full is reserved for heavier checks.",
    )
    parser.add_argument(
        "--skip-final-llm-evaluation",
        action="store_true",
        help="Skip the second LLM call and use a deterministic rule-based execution summary.",
    )
    parser.add_argument("--no-cache", action="store_true", help="Disable local Agent LLM planning cache for this run.")
    parser.add_argument("--refresh-cache", action="store_true", help="Ignore existing cache and replace it with a fresh LLM plan.")
    parser.add_argument("--workspace", default="workspace/generated-operators", help="Scaffold workspace parent.")
    parser.add_argument("--execute", action="store_true", help="Allow real execution for mutating tools.")
    parser.add_argument("--kind-deploy", action="store_true", help="Include profile-backed kind deployment after validation.")
    parser.add_argument(
        "--resume-existing",
        action="store_true",
        help="Skip scaffold creation when the target project already exists and continue patch/validation/deployment.",
    )
    args = parser.parse_args()

    if args.analyze_log and not args.log_dir:
        args.log_dir = args.analyze_log
    if args.log_dir:
        return run_log_analysis_agent(args)
    if not args.requirement:
        raise SystemExit("--requirement is required unless --log-dir or --analyze-log is provided.")
    return run_requirement_agent(args)


def run_requirement_agent(args: argparse.Namespace) -> int:
    total_started = time.perf_counter()
    requirement_path = Path(args.requirement)
    requirement_text = requirement_path.read_text(encoding="utf-8")
    profile = load_profile(Path(args.profile)) if args.profile else {}
    context = build_requirement_context(requirement_path, requirement_text, args.profile, profile, args.workspace)
    context["kindDeploymentRequested"] = bool(args.kind_deploy)
    context["resumeExisting"] = bool(args.resume_existing)
    log_dir = make_agent_log_dir()

    print("LLM Agent Orchestrator")
    print(f"Requirement: {context['requirement']}")
    print(f"Profile hint: {context['selectedProfile'].get('path') or '<none>'}")
    print(f"Primary intent: {context['intentAnalysis'].get('primaryIntent')}")
    print("Default safety mode: dry-run")
    print(f"Run level: {args.run_level}")

    planner_started = time.perf_counter()
    planner_result = call_requirement_planner(args, requirement_text, context)
    context["timings"]["llmPlanningSeconds"] = elapsed(planner_started)
    print_planner_cache_status(planner_result)
    if planner_result["error"]:
        execution = {"validatedToolCalls": [], "rejectedToolCalls": [], "deferredToolCalls": [], "toolResults": []}
        final_result = empty_final_result(planner_result["error"])
        summary = build_requirement_summary(args, context, planner_result, execution, final_result)
        summary["timings"] = finalize_timings(context, execution, total_started)
        summary["safetyEvaluation"] = build_requirement_safety_evaluation(args, context, execution, planner_result, None)
        summary["evidenceTrace"] = build_requirement_evidence_trace(summary)
        write_agent_artifacts(log_dir, summary, planner_result, context["retrievedKnowledge"], execution, final_result)
        report = render_requirement_report(summary)
        (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
        print(report)
        print(f"\nAgent logs: {log_dir}")
        return 2

    if args.kind_deploy:
        ensure_requested_tool_call(
            planner_result,
            "validation",
            args.mode,
            "kind deployment requires make generate, make manifests, and make test to pass first.",
        )
        ensure_requested_tool_call(
            planner_result,
            "kind_deployment",
            args.mode,
            "User explicitly requested profile-backed kind deployment after validation.",
        )
    execution = execute_planned_tools(context, args.mode, args.execute, planner_result)
    context["timings"].update(execution.get("timings") or {})
    initial_errors = collect_errors(execution["toolResults"])
    if planner_result["error"]:
        initial_errors.append(planner_result["error"])
    recovery_result = None
    failure_context = detect_failure_context(context, planner_result, execution, args)
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
        recovery_result = call_recovery_planner(context, planner_result, execution, failure_context, args)
        context["timings"]["recoveryPlanningSeconds"] = elapsed(recovery_started)
        final_result = empty_final_result("Execution failed; recovery plan generated and waiting for user approval.")
    else:
        if should_skip_final_llm_evaluation(args):
            context["timings"]["finalLlmEvaluationSeconds"] = 0.0
            final_result = rule_based_final_result(context, planner_result, execution, collect_warnings(execution["toolResults"], context), initial_errors, args)
        else:
            final_started = time.perf_counter()
            final_result = call_final_evaluator(context, planner_result, execution, collect_warnings(execution["toolResults"], context), initial_errors)
            context["timings"]["finalLlmEvaluationSeconds"] = elapsed(final_started)
    summary = build_requirement_summary(args, context, planner_result, execution, final_result, recovery_result, failure_context)
    summary["timings"] = finalize_timings(context, execution, total_started)
    summary["safetyEvaluation"] = build_requirement_safety_evaluation(args, context, execution, planner_result, failure_context)
    summary["evidenceTrace"] = build_requirement_evidence_trace(summary)
    write_agent_artifacts(log_dir, summary, planner_result, context["retrievedKnowledge"], execution, final_result, recovery_result)
    report = render_requirement_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 0 if not summary["errors"] else 1


def call_final_evaluator(
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    llm_output = planner_result.get("llmOutput") or {}
    llm_input = {
        "mode": "tool-result-evaluation",
        "requirementSummary": context["requirementSummary"],
        "plannedSteps": llm_output.get("plannedSteps") or [],
        "toolCalls": extract_tool_call_plan(llm_output),
        "validatedToolCalls": execution["validatedToolCalls"],
        "rejectedToolCalls": execution["rejectedToolCalls"],
        "deferredToolCalls": execution.get("deferredToolCalls") or [],
        "toolResults": execution["toolResults"],
        "generatedFiles": context["generatedFiles"],
        "warnings": warnings,
        "errors": errors,
    }
    try:
        output, exact_input, raw = evaluate_tool_results_with_llm(
            context["requirementSummary"],
            llm_output.get("plannedSteps") or [],
            extract_tool_call_plan(llm_output),
            execution["validatedToolCalls"],
            execution["rejectedToolCalls"],
            execution["toolResults"],
            context["generatedFiles"],
            warnings,
            errors,
        )
        validate_llm_output_schema("tool-result-evaluation", output, raw)
        return llm_result(True, exact_input, output, raw)
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM final evaluation failed."
        print(f"Final LLM evaluation failed: {message}")
        return llm_result(False, llm_input, {}, raw_from_exception(exc), message)


def call_recovery_planner(
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
    failure_context: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    deterministic_classification = deterministic_recovery_classification(failure_context)
    if deterministic_classification:
        scrubbed = scrub_failure_context(failure_context)
        policy = validate_recovery_plan(
            {"classification": deterministic_classification},
            scrubbed,
            context,
        )
        cfg = config_from_env()
        return {
            "requestedPlanner": "policy",
            "effectivePlanner": "deterministic-recovery-policy",
            "llmPlannerUsed": False,
            "localLLM": {"baseUrl": cfg.base_url, "model": cfg.model},
            "llmInput": {
                "mode": "recovery-planning",
                "skipped": True,
                "reason": f"Deterministic recovery classification: {deterministic_classification}",
                "failureContext": scrubbed,
            },
            "llmOutput": policy["validatedRecoveryPlan"],
            "rawOutput": "",
            "error": "",
            "skipped": True,
            "skipReason": deterministic_classification,
            "rawRecoveryPlan": {},
            "policyEvaluation": policy["policyEvaluation"],
            "rejectedRecoveryToolCalls": policy["rejectedRecoveryToolCalls"],
            "retrievedTroubleshootingDocs": [],
            "retrievalDetails": {},
        }

    query = build_failure_rag_query(failure_context)
    retrieval = perform_retrieval(query, limit=3, purpose="recovery")
    retrieved = retrieval["selectedContext"]
    successful = [item for item in execution["toolResults"] if item.get("exitCode") == 0]
    failed = failure_context.get("failedResult") or {}
    llm_input = {
        "mode": "recovery-planning",
        "requirementSummary": context["requirementSummary"],
        "toolPlan": extract_tool_call_plan(planner_result.get("llmOutput") or {}),
        "successfulToolResults": successful,
        "failedToolResult": failed,
        "failureContext": scrub_failure_context(failure_context),
        "retrievedDocs": retrieved,
        "agentMode": args.mode,
    }
    try:
        output, exact_input, raw = plan_recovery_with_llm(
            context["requirementSummary"],
            extract_tool_call_plan(planner_result.get("llmOutput") or {}),
            successful,
            failed,
            scrub_failure_context(failure_context),
            retrieved,
            args.mode,
        )
        validate_llm_output_schema("recovery-planning", output, raw)
        result = llm_result(True, exact_input, output, raw)
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM recovery planning failed."
        print(f"Recovery LLM planning failed: {message}")
        result = llm_result(False, llm_input, {}, raw_from_exception(exc), message)
        output = {}
    policy = validate_recovery_plan(output, scrub_failure_context(failure_context), context)
    result["rawRecoveryPlan"] = output
    result["llmOutput"] = policy["validatedRecoveryPlan"]
    result["policyEvaluation"] = policy["policyEvaluation"]
    result["rejectedRecoveryToolCalls"] = policy["rejectedRecoveryToolCalls"]
    result["retrievedTroubleshootingDocs"] = retrieved
    result["retrievalDetails"] = retrieval
    return result


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
    summary["timings"] = finalize_timings(context, execution, total_started)
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
    (log_dir / "agent-report.md").write_text(render_requirement_report(summary), encoding="utf-8")


def empty_final_result(error: str) -> dict[str, Any]:
    return {
        "requestedPlanner": "llm",
        "effectivePlanner": "none",
        "llmPlannerUsed": False,
        "localLLM": {
            "baseUrl": config_from_env().base_url,
            "model": config_from_env().model,
        },
        "llmInput": {},
        "llmOutput": {},
        "rawOutput": "",
        "error": error,
    }


def should_skip_final_llm_evaluation(args: argparse.Namespace) -> bool:
    return bool(args.skip_final_llm_evaluation or args.run_level == "fast")


def rule_based_final_result(
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, Any],
    warnings: list[str],
    errors: list[str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    tool_results = execution.get("toolResults") or []
    rejected = execution.get("rejectedToolCalls") or []
    failed = [item for item in tool_results if item.get("exitCode") != 0]
    if failed or errors:
        decision = "failed"
    elif rejected:
        decision = "partially-succeeded"
    else:
        decision = "succeeded"

    output = {
        "executionDecision": decision,
        "completedSteps": [str(item.get("tool")) for item in tool_results if item.get("exitCode") == 0],
        "failedSteps": [str(item.get("tool")) for item in failed],
        "generatedArtifacts": [path for path in context.get("generatedFiles", {}).values()],
        "validationResults": validation_results_from_tool_results(tool_results),
        "evidence": [
            f"{item.get('tool')} exitCode={item.get('exitCode')} status={item.get('status')}"
            for item in tool_results
        ],
        "warnings": warnings + (["Final LLM evaluation skipped by fast mode."] if args.run_level == "fast" else []),
        "recommendedNextActions": [
            "Run again with --run-level standard when a full LLM final evaluation is needed.",
            "Use --execute only after reviewing validated-tool-calls.json and safety-evaluation.json.",
        ],
        "beginnerSummary": "Fast mode used a deterministic summary from Tool exit codes instead of a second LLM call.",
    }
    return {
        "requestedPlanner": "llm",
        "effectivePlanner": "rule-based-fast-summary",
        "llmPlannerUsed": False,
        "localLLM": {
            "baseUrl": config_from_env().base_url,
            "model": config_from_env().model,
        },
        "llmInput": {
            "mode": "tool-result-evaluation",
            "skipped": True,
            "reason": "fast mode or --skip-final-llm-evaluation",
        },
        "llmOutput": output,
        "rawOutput": "",
        "error": "",
        "skipped": True,
        "skipReason": "fast mode" if args.run_level == "fast" else "--skip-final-llm-evaluation",
    }


def validation_results_from_tool_results(tool_results: list[dict[str, Any]]) -> dict[str, str]:
    results = {"makeGenerate": "skipped", "makeManifests": "skipped", "makeTest": "skipped"}
    for item in tool_results:
        if item.get("tool") != "validation":
            continue
        for step in item.get("steps") or []:
            target = step.get("target")
            status = "succeeded" if step.get("exitCode") == 0 else "failed"
            if target == "generate":
                results["makeGenerate"] = status
            elif target == "manifests":
                results["makeManifests"] = status
            elif target == "test":
                results["makeTest"] = status
    return results


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
    if not args.no_cache and not args.refresh_cache and cache["path"].is_file():
        try:
            cached = json.loads(cache["path"].read_text(encoding="utf-8"))
            result = llm_result(True, cached.get("llmInput") or llm_input, cached.get("llmOutput") or {}, cached.get("rawOutput") or "")
            result["cache"] = {
                "enabled": True,
                "hit": True,
                "key": cache["key"],
                "path": str(cache["path"]),
                "createdAt": cached.get("createdAt", ""),
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
        result = llm_result(True, exact_input, output, raw)
        result["cache"] = {
            "enabled": not args.no_cache,
            "hit": False,
            "key": cache["key"],
            "path": str(cache["path"]),
            "refreshed": bool(args.refresh_cache),
        }
        if not args.no_cache:
            write_requirement_plan_cache(cache["path"], exact_input, output, raw, result)
        return result
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM planner failed."
        print(f"LLM planner failed: {message}")
        result = llm_result(False, llm_input, {}, raw_from_exception(exc), message)
        result["cache"] = {
            "enabled": not args.no_cache,
            "hit": False,
            "key": cache["key"],
            "path": str(cache["path"]),
        }
        return result


def print_planner_cache_status(planner_result: dict[str, Any]) -> None:
    cache = planner_result.get("cache") or {}
    if not cache:
        return
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
    if any(isinstance(item, dict) and normalize_tool_name(str(item.get("tool") or "")) == tool for item in calls):
        return
    calls.append(
        {
            "tool": tool,
            "mode": "execute" if agent_mode == "execute" else "dry-run",
            "reason": reason,
            "source": "explicit-user-workflow-option",
        }
    )


def run_log_analysis_agent(args: argparse.Namespace) -> int:
    source_log_dir = Path(args.log_dir)
    source_summary_path = source_log_dir / "summary.json"
    if not source_summary_path.is_file():
        raise SystemExit(f"summary.json not found under log directory: {source_log_dir}")

    source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
    log_dir = make_agent_log_dir()

    print("LLM Agent Log Analysis")
    print(f"Source log dir: {source_log_dir}")
    print("\nCalling tool: log_analyzer")
    analyzer_result = tools.log_analyzer(str(source_log_dir))
    analyzer_result["tool"] = "log_analyzer"
    print(f"exitCode={analyzer_result['exitCode']} status={analyzer_result['status']}")

    analysis_path = source_log_dir / "analysis.md"
    analysis_text = analysis_path.read_text(encoding="utf-8") if analysis_path.is_file() else ""
    retrieval = perform_retrieval(build_log_rag_query(source_summary, analysis_text), limit=3, purpose="log-analysis")
    retrieved = retrieval["selectedContext"]
    planner_result = call_log_planner(source_summary, analysis_text, retrieved)

    errors = [] if analyzer_result["exitCode"] == 0 else ["log_analyzer failed"]
    if planner_result["error"]:
        errors.append("LLM planner failed")

    summary = {
        "mode": "log-analysis",
        "planner": "llm",
        "llmPlannerUsed": planner_result["llmPlannerUsed"],
        "localLLM": planner_result.get("localLLM") or {},
        "llmError": planner_result["error"],
        "sourceLogDir": str(source_log_dir),
        "sourceSummary": str(source_summary_path),
        "sourceAnalysis": str(analysis_path),
        "createdAt": now_iso(),
        "logAnalyzerResult": analyzer_result,
        "retrievedKnowledge": retrieved,
        "retrievalDetails": retrieval,
        "llmAnalysis": planner_result.get("llmOutput") or {},
        "ragEvidence": extract_list(planner_result.get("llmOutput") or {}, "ragEvidence"),
        "warnings": source_summary.get("warnings") or [],
        "errors": errors,
    }
    summary["safetyEvaluation"] = build_log_analysis_safety_evaluation(summary)
    summary["evidenceTrace"] = build_log_analysis_evidence_trace(summary)
    write_agent_artifacts(log_dir, summary, planner_result, retrieved, [analyzer_result])
    report = render_log_analysis_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 0 if not errors else 1


def call_log_planner(
    source_summary: dict[str, Any],
    analysis_text: str,
    retrieved: list[dict[str, Any]],
) -> dict[str, Any]:
    llm_input = {
        "mode": "log-analysis",
        "summary": source_summary,
        "analysisMd": analysis_text,
        "retrievedDocs": retrieved,
    }
    try:
        output, exact_input, raw = analyze_log_with_llm(source_summary, analysis_text, retrieved)
        validate_llm_output_schema("log-analysis", output, raw)
        return llm_result(True, exact_input, output, raw)
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM planner failed."
        print(f"LLM planner failed: {message}")
        return llm_result(False, llm_input, {}, raw_from_exception(exc), message)


def llm_result(
    used: bool,
    llm_input: dict[str, Any],
    output: dict[str, Any],
    raw: str,
    error: str = "",
) -> dict[str, Any]:
    return {
        "requestedPlanner": "llm",
        "effectivePlanner": "llm" if used else "none",
        "llmPlannerUsed": used,
        "localLLM": {
            "baseUrl": config_from_env().base_url,
            "model": config_from_env().model,
        },
        "llmInput": llm_input,
        "llmOutput": output,
        "rawOutput": raw,
        "error": error,
    }


def requirement_plan_cache_metadata(llm_input: dict[str, Any]) -> dict[str, Any]:
    cfg = config_from_env()
    payload = {
        "version": REQUIREMENT_PLAN_CACHE_VERSION,
        "localLLM": {"baseUrl": cfg.base_url, "model": cfg.model},
        "llmInput": llm_input,
    }
    key = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    path = AGENT_CACHE_ROOT / "llm-plans" / f"{key}.json"
    return {"key": key, "path": path}


def write_requirement_plan_cache(
    path: Path,
    llm_input: dict[str, Any],
    output: dict[str, Any],
    raw: str,
    planner_result: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "createdAt": now_iso(),
        "cacheVersion": REQUIREMENT_PLAN_CACHE_VERSION,
        "localLLM": planner_result.get("localLLM") or {},
        "llmInput": llm_input,
        "llmOutput": output,
        "rawOutput": raw,
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def build_requirement_context(
    requirement_path: Path,
    requirement_text: str,
    profile_path: str | None,
    profile: dict[str, Any],
    workspace: str,
) -> dict[str, Any]:
    timings: dict[str, Any] = {}
    rag_started = time.perf_counter()
    summary = summarize_requirement(requirement_text)
    intent = analyze_requirement_intent(requirement_text)
    profile_hint = select_profile_hint(requirement_text, profile_path, profile)
    kind = summary.get("kind") or "operator"
    kind_slug = kind.lower()
    retrieval = perform_retrieval(requirement_text, limit=requirement_rag_limit(), purpose="requirement")
    timings["ragRetrievalSeconds"] = elapsed(rag_started)
    retrieved = retrieval["selectedContext"]
    return {
        "requirement": str(requirement_path),
        "requirementSummary": summary,
        "intentAnalysis": intent,
        "missingInformation": missing_information(summary, requirement_text),
        "retrievedKnowledge": retrieved,
        "retrievalDetails": retrieval,
        "selectedProfile": profile_hint["selectedProfile"],
        "profileCandidates": profile_hint["profileCandidates"],
        "workspace": workspace,
        "targetProjectDir": str(Path(workspace) / infer_project_name(kind, f"generated/{kind_slug}-operator-spec.yaml")),
        "generatedFiles": {
            "operatorSpec": f"generated/{kind_slug}-operator-spec.yaml",
            "commandPlan": f"generated/{kind_slug}-command-plan.md",
        },
        "timings": timings,
    }


def perform_retrieval(query: str, limit: int = 3, purpose: str = "requirement") -> dict[str, Any]:
    details = retrieve_knowledge_detailed(query, limit=limit)
    selected = select_context(details, limit, purpose)
    return {
        "retrievalQuery": {"query": query},
        "retrievalMode": details.get("retrievalMode", ""),
        "vectorSearchResults": details.get("vectorSearchResults") or [],
        "keywordSearchResults": details.get("keywordSearchResults") or [],
        "hybridResults": details.get("hybridResults") or [],
        "rerankedResults": details.get("rerankedResults") or [],
        "selectedContext": selected[:limit],
        "fallbackUsed": bool(details.get("fallbackUsed")),
        "fallbackReason": details.get("fallbackReason", ""),
        "embeddingModel": details.get("embeddingModel", ""),
        "embeddingDimension": details.get("embeddingDimension"),
        "rerankerModel": details.get("rerankerModel", ""),
        "elapsedSeconds": details.get("elapsedSeconds"),
        "rerankerOutput": details.get("rerankerOutput") or {},
    }


def select_context(details: dict[str, Any], limit: int, purpose: str) -> list[dict[str, Any]]:
    pool = details.get("rerankedResults") or details.get("selectedContext") or details.get("hybridResults") or []
    selected: list[dict[str, Any]] = []
    used_sources: set[str] = set()

    def add_matching(categories: set[str], max_count: int, context_type: str) -> None:
        count = 0
        for item in pool:
            if count >= max_count or len(selected) >= limit:
                return
            source = str(item.get("sourcePath") or item.get("path") or "")
            if not source or source in used_sources:
                continue
            if str(item.get("category") or "") not in categories:
                continue
            row = dict(item)
            row["contextType"] = context_type
            row["reason"] = row.get("reason") or f"Selected for {purpose} context from {row.get('category')} document."
            selected.append(row)
            used_sources.add(source)
            count += 1

    if purpose == "requirement":
        add_matching({"guide", "troubleshooting"}, 2, "reference")
        add_matching({"example", "few-shot"}, 1, "few-shot")
    elif purpose in {"recovery", "log-analysis"}:
        add_matching({"troubleshooting", "guide"}, 2, "reference")
        add_matching({"few-shot", "example"}, 1, "few-shot")

    for item in pool:
        if len(selected) >= limit:
            break
        source = str(item.get("sourcePath") or item.get("path") or "")
        if not source or source in used_sources:
            continue
        row = dict(item)
        row["contextType"] = row.get("contextType") or ("few-shot" if row.get("category") in {"example", "few-shot"} else "reference")
        row["reason"] = row.get("reason") or f"Selected as fallback context for {purpose}."
        selected.append(row)
        used_sources.add(source)
    return selected[:limit]


def requirement_rag_limit() -> int:
    raw = os.environ.get("AGENT_REQUIREMENT_RAG_LIMIT", "2")
    try:
        return max(1, min(3, int(raw)))
    except ValueError:
        return 2


def detect_failure_context(
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
    args: argparse.Namespace,
) -> dict[str, Any] | None:
    if execution["rejectedToolCalls"]:
        return {
            "failedTool": "tool-validation",
            "failedStep": "rejectedToolCalls",
            "exitCode": 2,
            "command": [],
            "stdoutTail": "",
            "stderrTail": json.dumps(execution["rejectedToolCalls"], ensure_ascii=False),
            "generatedArtifacts": existing_artifacts(context),
            "missingArtifacts": missing_artifacts(context),
            "previousSuccessfulSteps": successful_step_names(execution["toolResults"]),
            "workspace": context["workspace"],
            "targetProjectDir": context["targetProjectDir"],
            "failedResult": {
                "tool": "tool-validation",
                "exitCode": 2,
                "status": "failed",
                "stderr": json.dumps(execution["rejectedToolCalls"], ensure_ascii=False),
            },
        }

    for result in execution["toolResults"]:
        if result.get("exitCode") != 0:
            failed_step = (
                (result.get("deploymentSummary") or {}).get("failedStep")
                or failed_validation_step(result)
            )
            return {
                "failedTool": result.get("tool"),
                "failedStep": failed_step or result.get("tool"),
                "exitCode": result.get("exitCode"),
                "command": result.get("command"),
                "stdoutTail": tail_lines(str(result.get("stdout") or ""), 100),
                "stderrTail": tail_lines(str(result.get("stderr") or ""), 100),
                "generatedArtifacts": existing_artifacts(context),
                "missingArtifacts": missing_artifacts(context),
                "previousSuccessfulSteps": successful_step_names(execution["toolResults"], stop_at=result.get("tool")),
                "workspace": context["workspace"],
                "targetProjectDir": context["targetProjectDir"],
                "agentMode": args.mode,
                "failedResult": result,
            }

    missing = missing_artifacts(context)
    if args.mode == "execute" and missing:
        return {
            "failedTool": "artifact-check",
            "failedStep": "expected artifact missing",
            "exitCode": 2,
            "command": [],
            "stdoutTail": "",
            "stderrTail": "Missing expected artifacts: " + ", ".join(missing),
            "generatedArtifacts": existing_artifacts(context),
            "missingArtifacts": missing,
            "previousSuccessfulSteps": successful_step_names(execution["toolResults"]),
            "workspace": context["workspace"],
            "targetProjectDir": context["targetProjectDir"],
            "agentMode": args.mode,
            "failedResult": {
                "tool": "artifact-check",
                "exitCode": 2,
                "status": "failed",
                "stderr": "Missing expected artifacts: " + ", ".join(missing),
            },
        }
    return None


def failed_validation_step(result: dict[str, Any]) -> str:
    if result.get("tool") != "validation":
        return ""
    for step in result.get("steps") or []:
        if step.get("exitCode") != 0:
            return f"make {step.get('target')}"
    return "validation"


def successful_step_names(results: list[dict[str, Any]], stop_at: str | None = None) -> list[str]:
    names = []
    for item in results:
        if stop_at and item.get("tool") == stop_at:
            break
        if item.get("exitCode") == 0 and item.get("tool"):
            names.append(str(item["tool"]))
    return names


def expected_artifacts(context: dict[str, Any]) -> list[str]:
    target = Path(context["targetProjectDir"])
    kind = context["requirementSummary"].get("kind") or ""
    version = context["requirementSummary"].get("version") or "v1alpha1"
    group = context["requirementSummary"].get("group") or ""
    lower_kind = kind.lower()
    return [
        context["generatedFiles"]["operatorSpec"],
        context["generatedFiles"]["commandPlan"],
        str(target / "api" / version / f"{lower_kind}_types.go"),
        str(target / "config" / "crd"),
        str(target / "config" / "rbac" / "role.yaml"),
        str(target / "config" / "samples" / f"{group}_{version}_{lower_kind}.yaml"),
    ]


def existing_artifacts(context: dict[str, Any]) -> list[str]:
    return [path for path in expected_artifacts(context) if Path(path).exists()]


def missing_artifacts(context: dict[str, Any]) -> list[str]:
    return [path for path in expected_artifacts(context) if not Path(path).exists()]


def tail_lines(text: str, count: int) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-count:])


def build_failure_rag_query(failure_context: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Kubebuilder Operator failure recovery",
            str(failure_context.get("failedTool") or ""),
            str(failure_context.get("failedStep") or ""),
            str(failure_context.get("exitCode") or ""),
            str(failure_context.get("stdoutTail") or ""),
            str(failure_context.get("stderrTail") or ""),
        ]
    )


def build_requirement_summary(
    args: argparse.Namespace,
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
    final_result: dict[str, Any],
    recovery_result: dict[str, Any] | None = None,
    failure_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tool_results = execution["toolResults"]
    errors = collect_errors(tool_results)
    if planner_result["error"]:
        errors.append(planner_result["error"])
    if final_result.get("error"):
        errors.append(final_result["error"])
    if failure_context and "Execution failed; recovery plan generated" in errors:
        pass
    if planner_result["llmPlannerUsed"] and not execution["validatedToolCalls"]:
        errors.append("LLM output did not include supported toolCalls.")
    if failure_context:
        errors = [item for item in errors if item != "Execution failed; recovery plan generated and waiting for user approval."]
    return {
        "mode": "requirement-planning",
        "requirement": context["requirement"],
        "profile": args.profile or "",
        "planner": "llm",
        "llmPlannerUsed": planner_result["llmPlannerUsed"],
        "localLLM": planner_result.get("localLLM") or {},
        "llmError": planner_result["error"],
        "plannerCache": planner_result.get("cache") or {},
        "agentMode": args.mode,
        "runLevel": args.run_level,
        "skipFinalLlmEvaluation": bool(args.skip_final_llm_evaluation or args.run_level == "fast"),
        "executeAllowed": bool(args.execute),
        "kindDeploymentRequested": bool(args.kind_deploy),
        "resumeExisting": bool(args.resume_existing),
        "createdAt": now_iso(),
        "requirementSummary": context["requirementSummary"],
        "intentAnalysis": context["intentAnalysis"],
        "missingInformation": context["missingInformation"],
        "clarifyingQuestions": clarifying_questions(context["missingInformation"], context["requirementSummary"]),
        "retrievedKnowledge": context["retrievedKnowledge"],
        "retrievalDetails": context.get("retrievalDetails") or {},
        "selectedProfile": context["selectedProfile"],
        "profileCandidates": context["profileCandidates"],
        "profilePolicy": {
            "role": "hint-only",
            "message": "Profiles are optional hints for defaults, examples, and validation rules. The Agent plans from the current requirement text first.",
        },
        "llmPlan": planner_result.get("llmOutput") or {},
        "llmReasoning": extract_list(planner_result.get("llmOutput") or {}, "reasoning"),
        "ragEvidence": extract_list(planner_result.get("llmOutput") or {}, "ragEvidence"),
        "toolCallPlan": extract_tool_call_plan(planner_result.get("llmOutput") or {}),
        "validatedToolCalls": execution["validatedToolCalls"],
        "rejectedToolCalls": execution["rejectedToolCalls"],
        "deferredToolCalls": execution.get("deferredToolCalls") or [],
        "generatedFiles": context["generatedFiles"],
        "toolResults": tool_results,
        "finalLLM": {
            "llmPlannerUsed": final_result.get("llmPlannerUsed"),
            "localLLM": final_result.get("localLLM") or {},
            "error": final_result.get("error") or "",
            "output": final_result.get("llmOutput") or {},
        },
        "failureContext": scrub_failure_context(failure_context) if failure_context else {},
        "recovery": {
            "waitingForUserApproval": bool(failure_context),
            "llmPlannerUsed": (recovery_result or {}).get("llmPlannerUsed"),
            "localLLM": (recovery_result or {}).get("localLLM") or {},
            "error": (recovery_result or {}).get("error") or "",
            "rawPlan": (recovery_result or {}).get("rawRecoveryPlan") or {},
            "plan": (recovery_result or {}).get("llmOutput") or {},
            "policyEvaluation": (recovery_result or {}).get("policyEvaluation") or {},
            "rejectedRecoveryToolCalls": (recovery_result or {}).get("rejectedRecoveryToolCalls") or [],
            "retrievedTroubleshootingDocs": (recovery_result or {}).get("retrievedTroubleshootingDocs") or [],
            "retrievalDetails": (recovery_result or {}).get("retrievalDetails") or {},
        },
        "warnings": collect_warnings(tool_results, context),
        "errors": errors,
        "nextRecommendedActions": next_actions(context, tool_results, planner_result, final_result),
    }


def build_requirement_safety_evaluation(
    args: argparse.Namespace,
    context: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
    planner_result: dict[str, Any],
    failure_context: dict[str, Any] | None,
) -> dict[str, Any]:
    allowed_tools = [
        "spec_generator",
        "command_planner",
        "scaffold_runner",
        "artifact_patcher",
        "validation",
        "e2e_runner",
        "kind_deployment",
    ]
    mutating_tools = {"scaffold_runner", "artifact_patcher", "e2e_runner", "kind_deployment"}
    validated = execution.get("validatedToolCalls") or []
    rejected = execution.get("rejectedToolCalls") or []
    deferred = execution.get("deferredToolCalls") or []
    forced_dry_run = [
        item
        for item in validated
        if item.get("tool") in mutating_tools
        and item.get("effectiveMode") == "dry-run"
        and not item.get("executeAllowed")
    ]
    return {
        "llmProviderPolicy": {
            "status": "passed" if planner_result.get("llmPlannerUsed") else "failed",
            "rule": "Only Ollama local LLM planner is supported; mock/OpenAI fallback is not used.",
            "model": (planner_result.get("localLLM") or {}).get("model"),
            "baseUrl": (planner_result.get("localLLM") or {}).get("baseUrl"),
            "evidence": "plannerResult.llmPlannerUsed and plannerResult.localLLM",
        },
        "toolAllowlist": {
            "status": "passed" if not rejected else "blocked",
            "allowedTools": allowed_tools,
            "rejectedCount": len(rejected),
            "rejectedToolCalls": rejected,
            "evidence": "rejected-tool-calls.json",
        },
        "executionModeGate": {
            "status": "passed",
            "agentMode": args.mode,
            "executeFlag": bool(args.execute),
            "forcedDryRunTools": [item.get("tool") for item in forced_dry_run],
            "rule": "--execute is required before mutating tools can perform real changes.",
            "evidence": "validated-tool-calls.json",
        },
        "pathSafety": {
            "status": "passed" if is_inside_repo(Path(context["workspace"])) and is_inside_repo(Path(context["targetProjectDir"])) else "failed",
            "workspace": context["workspace"],
            "targetProjectDir": context["targetProjectDir"],
            "rule": "workspace and target project paths must stay inside the repository root.",
            "evidence": "validated Tool arguments",
        },
        "validationCommandAllowlist": {
            "status": "passed",
            "allowedTargets": ["make generate", "make manifests", "make test"],
            "rule": "The validation Tool only accepts generate, manifests, and test targets.",
            "evidence": "agent/tools/langchain_wrappers.py validation()",
        },
        "deferredToolPolicy": {
            "status": "passed",
            "deferredCount": len(deferred),
            "deferredToolCalls": deferred,
            "rule": "Tools that require a scaffolded project may be deferred during dry-run.",
            "evidence": "deferred-tool-calls.json",
        },
        "recoveryApprovalGate": {
            "status": "waiting-for-user-approval" if failure_context else "not-needed",
            "rule": "Recovery Tool calls are never executed automatically.",
            "evidence": "validated-recovery-plan.json" if failure_context else "",
        },
    }


def build_log_analysis_safety_evaluation(summary: dict[str, Any]) -> dict[str, Any]:
    analyzer = summary.get("logAnalyzerResult") or {}
    return {
        "llmProviderPolicy": {
            "status": "passed" if summary.get("llmPlannerUsed") else "failed",
            "rule": "Only Ollama local LLM planner is supported; mock/OpenAI fallback is not used.",
            "model": (summary.get("localLLM") or {}).get("model"),
            "baseUrl": (summary.get("localLLM") or {}).get("baseUrl"),
        },
        "readOnlyAnalysis": {
            "status": "passed",
            "rule": "Log analysis mode only reads existing logs and invokes log_analyzer.",
            "sourceLogDir": summary.get("sourceLogDir"),
            "command": analyzer.get("command"),
        },
        "toolAllowlist": {
            "status": "passed" if analyzer.get("tool") == "log_analyzer" else "failed",
            "allowedTools": ["log_analyzer"],
            "executedTool": analyzer.get("tool"),
        },
    }


def build_requirement_evidence_trace(summary: dict[str, Any]) -> dict[str, Any]:
    final_output = (summary.get("finalLLM") or {}).get("output") or {}
    recovery = summary.get("recovery") or {}
    trace = {
        "requirementEvidence": {
            "source": summary.get("requirement"),
            "parsedSummary": summary.get("requirementSummary") or {},
            "intentAnalysis": summary.get("intentAnalysis") or {},
            "missingInformation": summary.get("missingInformation") or [],
        },
        "profileHintEvidence": {
            "policy": summary.get("profilePolicy") or {},
            "selectedProfile": summary.get("selectedProfile") or {},
            "profileCandidates": summary.get("profileCandidates") or [],
        },
        "ragEvidence": build_rag_trace(summary.get("retrievalDetails") or {}, summary.get("ragEvidence") or []),
        "llmPlanningEvidence": {
            "planner": "llm",
            "reasoning": summary.get("llmReasoning") or [],
            "toolCallPlan": summary.get("toolCallPlan") or [],
            "risks": (summary.get("llmPlan") or {}).get("risks") or [],
            "nextActions": (summary.get("llmPlan") or {}).get("nextActions") or [],
        },
        "toolValidationEvidence": {
            "validatedToolCalls": summary.get("validatedToolCalls") or [],
            "rejectedToolCalls": summary.get("rejectedToolCalls") or [],
            "deferredToolCalls": summary.get("deferredToolCalls") or [],
        },
        "executionEvidence": build_execution_trace(summary.get("toolResults") or []),
        "finalJudgmentEvidence": {
            "llmOutput": final_output,
            "evidence": final_output.get("evidence") or [],
            "warnings": final_output.get("warnings") or [],
            "decision": final_output.get("executionDecision") or "",
        },
        "recoveryEvidence": {
            "waitingForUserApproval": bool(recovery.get("waitingForUserApproval")),
            "policyEvaluation": recovery.get("policyEvaluation") or {},
            "validatedRecoveryToolCalls": (recovery.get("plan") or {}).get("validatedRecoveryToolCalls") or [],
            "rejectedRecoveryToolCalls": recovery.get("rejectedRecoveryToolCalls") or [],
        },
    }
    return trace


def build_log_analysis_evidence_trace(summary: dict[str, Any]) -> dict[str, Any]:
    llm_analysis = summary.get("llmAnalysis") or {}
    return {
        "sourceLogEvidence": {
            "sourceLogDir": summary.get("sourceLogDir"),
            "sourceSummary": summary.get("sourceSummary"),
            "sourceAnalysis": summary.get("sourceAnalysis"),
            "warnings": summary.get("warnings") or [],
        },
        "ragEvidence": build_rag_trace(summary.get("retrievalDetails") or {}, summary.get("ragEvidence") or []),
        "toolEvidence": build_execution_trace([summary.get("logAnalyzerResult") or {}]),
        "llmJudgmentEvidence": {
            "decision": llm_analysis.get("decision") or "",
            "classification": llm_analysis.get("classification") or "",
            "rootCause": llm_analysis.get("rootCause") or "",
            "evidence": llm_analysis.get("evidence") or [],
            "recommendedFixes": llm_analysis.get("recommendedFixes") or [],
        },
    }


def build_rag_trace(retrieval_details: dict[str, Any], llm_rag_evidence: list[Any]) -> dict[str, Any]:
    selected = retrieval_details.get("selectedContext") or []
    return {
        "query": retrieval_details.get("retrievalQuery") or {},
        "retrievalMode": retrieval_details.get("retrievalMode") or "",
        "fallbackUsed": bool(retrieval_details.get("fallbackUsed")),
        "fallbackReason": retrieval_details.get("fallbackReason") or "",
        "embeddingModel": retrieval_details.get("embeddingModel") or "",
        "rerankerModel": retrieval_details.get("rerankerModel") or "",
        "selectedDocuments": [
            {
                "path": item.get("sourcePath") or item.get("path"),
                "title": item.get("title"),
                "category": item.get("category"),
                "contextType": item.get("contextType"),
                "score": item.get("combinedScore", item.get("score")),
                "matchedKeywords": item.get("matchedKeywords") or [],
                "selectionReason": item.get("reason") or "",
            }
            for item in selected
            if isinstance(item, dict)
        ],
        "llmClaimedUsage": llm_rag_evidence,
    }


def build_execution_trace(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace = []
    for item in tool_results:
        if not isinstance(item, dict):
            continue
        trace.append(
            {
                "tool": item.get("tool"),
                "command": item.get("command"),
                "cwd": item.get("cwd"),
                "status": item.get("status"),
                "exitCode": item.get("exitCode"),
                "stdoutEvidence": tail_lines(str(item.get("stdout") or ""), 8),
                "stderrEvidence": tail_lines(str(item.get("stderr") or ""), 8),
                "steps": [
                    {
                        "target": step.get("target"),
                        "status": step.get("status"),
                        "exitCode": step.get("exitCode"),
                    }
                    for step in item.get("steps") or []
                    if isinstance(step, dict)
                ],
            }
        )
    return trace


def load_profile(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"profile YAML must be a mapping: {path}")
    data["_profilePath"] = str(path)
    return data


def summarize_requirement(text: str) -> dict[str, Any]:
    kind = find_value(text, r"kind\s*(?:은|는|:|=)\s*([A-Z][A-Za-z0-9]*)") or find_value(
        text, r"([A-Z][A-Za-z0-9]*)\s*라는\s+Kubernetes Custom Resource"
    )
    domain = find_value(text, r"domain\s*(?:은|는|:|=)\s*([a-z0-9.-]+\.[a-z0-9.-]+)")
    group = find_value(text, r"group\s*(?:은|는|:|=)\s*([a-z][a-z0-9-]*)")
    version = find_value(text, r"version\s*(?:은|는|:|=)\s*(v[0-9]+(?:alpha[0-9]+|beta[0-9]+)?)")
    managed = sorted(set(re.findall(r"\b(ConfigMap|Deployment|StatefulSet|Service|Job|CronJob|Secret|PVC|PersistentVolumeClaim|Pod)\b", text)))
    spec_fields = parse_field_names(text, "spec")
    status_fields = parse_field_names(text, "status")
    return {
        "kind": kind,
        "domain": domain,
        "group": group,
        "version": version,
        "managedResources": managed,
        "specFields": spec_fields,
        "statusFields": status_fields,
        "shortSummary": f"{kind or 'Unknown'} Operator 요구사항: {', '.join(managed) or '관리 리소스 미확인'} 관리 흐름.",
    }


def missing_information(summary: dict[str, Any], text: str) -> list[str]:
    checks = {
        "kind": summary.get("kind"),
        "domain": summary.get("domain"),
        "group": summary.get("group"),
        "version": summary.get("version"),
        "spec fields": summary.get("specFields"),
        "status fields": summary.get("statusFields"),
        "managed Kubernetes resource": summary.get("managedResources"),
        "validation commands": "make generate" in text and "make manifests" in text and "make test" in text,
    }
    return [name for name, value in checks.items() if not value]


def clarifying_questions(missing: list[str], summary: dict[str, Any]) -> list[str]:
    question_map = {
        "kind": "Custom Resource 이름(kind)을 무엇으로 할까요? 예: BackupPolicy, WebService, SecretSync",
        "domain": "API domain은 무엇으로 할까요? 예: sample.io, platform.internal",
        "group": "API group은 무엇으로 할까요? 예: app, batch, security",
        "version": "API version은 무엇으로 할까요? 보통 처음에는 v1alpha1을 사용합니다.",
        "spec fields": "사용자가 Custom Resource에 입력해야 하는 spec 필드는 무엇인가요?",
        "status fields": "kubectl로 확인하고 싶은 status 필드는 무엇인가요?",
        "managed Kubernetes resource": "Controller가 생성하거나 관리할 Kubernetes 리소스는 무엇인가요? 예: ConfigMap, Secret, Deployment, Job",
        "validation commands": "검증 명령은 make generate, make manifests, make test를 사용해도 될까요?",
    }
    questions = [question_map[item] for item in missing if item in question_map]
    managed = summary.get("managedResources") or []
    if managed and "status fields" in missing:
        questions.append(f"{', '.join(managed)} 상태 중 어떤 값을 status에 반영할까요?")
    return questions


def parse_field_names(text: str, section: str) -> list[str]:
    match = re.search(rf"{section}\s*에는.*?(?=\n\n|status에는|Controller는|검증 명령|$)", text, flags=re.DOTALL)
    block = match.group(0) if match else ""
    return re.findall(r"^\s*-\s*([a-z][A-Za-z0-9]*)\s*:", block, flags=re.MULTILINE)


def find_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def infer_project_name(kind: str, spec_path: str) -> str:
    path = Path(spec_path)
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                project = data.get("project") or {}
                if project.get("name"):
                    return str(project["name"])
        except yaml.YAMLError:
            pass
    if not kind:
        return "operator"
    return camel_to_kebab(kind) + "-operator"


def camel_to_kebab(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", value).lower()


def build_log_rag_query(summary: dict[str, Any], analysis_text: str) -> str:
    return "\n".join(
        [
            "Kubebuilder Operator troubleshooting log analysis",
            str(summary.get("failedStep") or "succeeded"),
            " ".join(str(item) for item in summary.get("warnings") or []),
            json.dumps(summary.get("jobSpecValidation") or {}, ensure_ascii=False),
            analysis_text[:2000],
        ]
    )


def collect_warnings(tool_results: list[dict[str, Any]], context: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if context["missingInformation"]:
        warnings.append("Requirement has missing or weakly inferred information: " + ", ".join(context["missingInformation"]))
    for result in tool_results:
        if "Warnings:" in result.get("stdout", ""):
            warnings.append(f"{result['tool']} reported warnings.")
    return warnings


def collect_errors(tool_results: list[dict[str, Any]]) -> list[str]:
    return [f"{result['tool']} failed with exit code {result['exitCode']}" for result in tool_results if result["exitCode"] != 0]


def next_actions(
    context: dict[str, Any],
    tool_results: list[dict[str, Any]],
    planner_result: dict[str, Any],
    final_result: dict[str, Any] | None = None,
) -> list[str]:
    final_actions = ((final_result or {}).get("llmOutput") or {}).get("recommendedNextActions") or []
    if final_actions:
        return [str(item) for item in final_actions if item]
    llm_actions = (planner_result.get("llmOutput") or {}).get("nextActions") or []
    actions = [str(item) for item in llm_actions if item]
    if any(result["exitCode"] != 0 for result in tool_results):
        actions.insert(0, "실패한 Tool의 stderr와 생성된 summary를 먼저 확인합니다.")
    if planner_result["error"]:
        actions.append("Ollama local LLM 서버와 모델 상태를 확인합니다.")
    if not actions:
        actions = [
            f"검토: {context['generatedFiles']['commandPlan']}",
            f"scaffold preflight: python3 agent/tools/scaffold_runner.py --input {context['generatedFiles']['operatorSpec']} --workspace {context['workspace']} --preflight",
        ]
    return actions


def render_requirement_report(summary: dict[str, Any]) -> str:
    req = summary["requirementSummary"]
    lines = [
        "# Agent Run Report",
        "",
        "## Planner",
        "",
        "- Planner: `llm`",
        f"- Local LLM endpoint: `{summary.get('localLLM', {}).get('baseUrl') or 'unknown'}`",
        f"- Local LLM model: `{summary.get('localLLM', {}).get('model') or 'unknown'}`",
        f"- LLM planner used: `{summary.get('llmPlannerUsed')}`",
        f"- LLM error: `{summary.get('llmError') or 'none'}`",
        f"- Planner cache hit: `{(summary.get('plannerCache') or {}).get('hit', False)}`",
        f"- Planner cache path: `{(summary.get('plannerCache') or {}).get('path', 'none')}`",
        f"- Run level: `{summary.get('runLevel') or 'standard'}`",
        f"- Final LLM evaluation skipped: `{summary.get('skipFinalLlmEvaluation')}`",
        "",
        "## Timings",
        "",
        *format_timings(summary.get("timings") or {}),
        "",
        "## Requirement Summary",
        "",
        f"- Kind: `{req.get('kind') or 'unknown'}`",
        f"- Domain: `{req.get('domain') or 'unknown'}`",
        f"- Group: `{req.get('group') or 'unknown'}`",
        f"- Version: `{req.get('version') or 'unknown'}`",
        f"- Managed resources: `{', '.join(req.get('managedResources') or []) or 'unknown'}`",
        f"- Spec fields: `{', '.join(req.get('specFields') or []) or 'none'}`",
        f"- Status fields: `{', '.join(req.get('statusFields') or []) or 'none'}`",
        "",
        "## Requirement Intent",
        "",
        f"- Primary intent: `{(summary.get('intentAnalysis') or {}).get('primaryIntent') or 'unknown'}`",
        f"- Confidence: `{(summary.get('intentAnalysis') or {}).get('confidence') or 'unknown'}`",
        f"- Managed resource hints: `{', '.join((summary.get('intentAnalysis') or {}).get('managedResourceHints') or []) or 'none'}`",
        "",
        "The Agent is not fixed to AppConfig, TrainingJob, RedisCache, or any single profile. The requirement text is the source of truth; profiles are optional hints for defaults and validation rules.",
        "",
        "## Missing Information Check",
        "",
        *([f"- {item}" for item in summary["missingInformation"]] or ["- No critical missing information found."]),
        "",
        "## Clarifying Questions",
        "",
        *([f"- {item}" for item in summary.get("clarifyingQuestions") or []] or ["- No clarifying questions are needed before dry-run."]),
        "",
        "## Retrieved Knowledge",
        "",
    ]
    lines.extend(format_retrieved_docs(summary["retrievedKnowledge"]))
    if summary.get("llmPlan"):
        lines.extend(["", "## LLM Planner Output", "", "```json", json.dumps(summary["llmPlan"], indent=2, ensure_ascii=False), "```"])

    lines.extend(["", "## AI Reasoning", ""])
    lines.extend([f"- {item}" for item in summary.get("llmReasoning") or []] or ["- LLM reasoning was not generated."])

    lines.extend(["", "## RAG Evidence Used By LLM", ""])
    lines.extend(format_rag_evidence(summary.get("ragEvidence") or []))

    lines.extend(["", "## Evidence Trace", ""])
    lines.extend(format_evidence_trace(summary.get("evidenceTrace") or {}))

    lines.extend(["", "## Tool Call Plan From LLM", ""])
    lines.extend(format_tool_call_plan(summary.get("toolCallPlan") or []))

    lines.extend(["", "## Tool Call Validation", ""])
    lines.extend(format_validated_tool_calls(summary.get("validatedToolCalls") or []))
    rejected = summary.get("rejectedToolCalls") or []
    if rejected:
        lines.extend(["", "## Rejected Tool Calls", ""])
        lines.extend(format_rejected_tool_calls(rejected))
    deferred = summary.get("deferredToolCalls") or []
    if deferred:
        lines.extend(["", "## Deferred Tool Calls", ""])
        lines.extend(format_rejected_tool_calls(deferred))

    lines.extend(["", "## Safety Evaluation", ""])
    lines.extend(format_safety_evaluation(summary.get("safetyEvaluation") or {}))

    profile = summary["selectedProfile"]
    lines.extend(
        [
            "",
            "## Profile Hint",
            "",
            f"- Path: `{profile.get('path') or 'none'}`",
            f"- Name: `{profile.get('name') or 'none'}`",
            f"- Selection mode: `{profile.get('selectionMode') or 'unknown'}`",
            f"- Reason: {profile.get('reason') or 'not specified'}",
            f"- Managed resources: `{', '.join(profile.get('managedResources') or []) or 'none'}`",
            "- Role: `hint-only`",
            "",
            "### Profile Candidates",
            "",
        ]
    )
    candidates = summary.get("profileCandidates") or []
    if candidates:
        for item in candidates[:5]:
            lines.append(
                f"- `{item.get('name') or 'unknown'}` score=`{item.get('score', 0)}` path=`{item.get('path') or ''}` reason={item.get('reason') or ''}"
            )
    else:
        lines.append("- No profile candidates were selected. Generic Agent core still plans from the requirement.")
    lines.extend(
        [
            "",
            "## Tool Execution Results",
            "",
        ]
    )
    if summary["toolResults"]:
        for result in summary["toolResults"]:
            lines.append(f"- `{result['tool']}`: {result['status']} exitCode={result['exitCode']}")
            lines.append(f"  - command: `{' '.join(result['command'])}`")
    else:
        lines.append("- No tools were executed.")

    deployment_results = [
        item.get("deploymentSummary") or {}
        for item in summary.get("toolResults") or []
        if item.get("tool") == "kind_deployment"
    ]
    if deployment_results:
        deployment = deployment_results[-1]
        lines.extend(
            [
                "",
                "## Kind Deployment Result",
                "",
                f"- Status: `{deployment.get('status') or 'unknown'}`",
                f"- Cluster: `{deployment.get('clusterName') or 'unknown'}`",
                f"- Validator: `{(deployment.get('validator') or {}).get('name') or 'unknown'}`",
                f"- Failed step: `{deployment.get('failedStep') or 'none'}`",
                f"- Log directory: `{deployment.get('logDir') or 'unknown'}`",
                f"- Checks: `{', '.join((deployment.get('checks') or {}).keys()) or 'none'}`",
            ]
        )

    recovery = summary.get("recovery") or {}
    if recovery.get("waitingForUserApproval"):
        plan = recovery.get("plan") or {}
        lines.extend(
            [
                "",
                "## Recovery Plan",
                "",
                "- Status: `Waiting for user approval`",
                f"- decision: `{plan.get('decision') or 'unknown'}`",
                f"- classification: `{plan.get('classification') or 'unknown'}`",
                f"- rootCause: {plan.get('rootCause') or 'unknown'}",
                "",
                "### Evidence",
                "",
            ]
        )
        lines.extend([f"- {item}" for item in plan.get("evidence") or []] or ["- No evidence was generated."])
        lines.extend(["", "### Proposed Fixes", ""])
        lines.extend([f"- {item}" for item in plan.get("proposedFixes") or []] or ["- No proposed fixes were generated."])
        lines.extend(["", "### Validated Recovery Tool Calls", ""])
        recovery_calls = plan.get("validatedRecoveryToolCalls") or plan.get("recoveryToolCalls") or []
        if recovery_calls:
            for item in recovery_calls:
                if isinstance(item, dict):
                    lines.append(
                        f"- `{item.get('tool')}` mode=`{item.get('mode')}` requiresApproval=`{item.get('requiresApproval')}`"
                    )
                    lines.append(f"  - reason: {item.get('reason') or 'not specified'}")
                    if item.get("expectedEffect"):
                        lines.append(f"  - expectedEffect: {item.get('expectedEffect')}")
                    if item.get("verificationStep"):
                        lines.append(f"  - verificationStep: {item.get('verificationStep')}")
        else:
            lines.append("- No recovery Tool calls were generated.")
        rejected_recovery = plan.get("rejectedRecoveryToolCalls") or recovery.get("rejectedRecoveryToolCalls") or []
        if rejected_recovery:
            lines.extend(["", "### Rejected Recovery Tool Calls", ""])
            for item in rejected_recovery:
                if isinstance(item, dict):
                    lines.append(f"- `{item.get('tool')}`: {item.get('reason')}")
        lines.extend(["", "No recovery Tool was executed. Waiting for user approval."])

    final_output = (summary.get("finalLLM") or {}).get("output") or {}
    lines.extend(["", "## Final LLM Evaluation", ""])
    if final_output:
        lines.extend(
            [
                f"- executionDecision: `{final_output.get('executionDecision') or 'unknown'}`",
                f"- completedSteps: `{', '.join(str(item) for item in final_output.get('completedSteps') or []) or 'none'}`",
                f"- failedSteps: `{', '.join(str(item) for item in final_output.get('failedSteps') or []) or 'none'}`",
                f"- validationResults: `{json.dumps(final_output.get('validationResults') or {}, ensure_ascii=False)}`",
                "",
                "```json",
                json.dumps(final_output, indent=2, ensure_ascii=False),
                "```",
            ]
        )
    else:
        final_error = (summary.get("finalLLM") or {}).get("error") or "Final LLM evaluation was not generated."
        lines.append(f"- {final_error}")

    generated = summary["generatedFiles"]
    lines.extend(
        [
            "",
            "## Generated Files",
            "",
            f"- Operator spec: `{generated['operatorSpec']}`",
            f"- Command plan: `{generated['commandPlan']}`",
            "",
            "## Warnings / Errors",
            "",
        ]
    )
    lines.extend([f"- Warning: {item}" for item in summary["warnings"]] or ["- Warnings: none"])
    lines.extend([f"- Error: {item}" for item in summary["errors"]] or ["- Errors: none"])
    lines.extend(["", "## Next Recommended Actions", ""])
    lines.extend([f"- {item}" for item in summary["nextRecommendedActions"]])
    return "\n".join(lines) + "\n"


def render_log_analysis_report(summary: dict[str, Any]) -> str:
    llm_analysis = summary.get("llmAnalysis") or {}
    lines = [
        "# Agent Log Analysis Report",
        "",
        "## Planner",
        "",
        "- Planner: `llm`",
        f"- Local LLM endpoint: `{summary.get('localLLM', {}).get('baseUrl') or 'unknown'}`",
        f"- Local LLM model: `{summary.get('localLLM', {}).get('model') or 'unknown'}`",
        f"- LLM planner used: `{summary.get('llmPlannerUsed')}`",
        f"- LLM error: `{summary.get('llmError') or 'none'}`",
        "",
        "## Overall Result",
        "",
        f"- Source log dir: `{summary['sourceLogDir']}`",
        f"- Source analysis: `{summary['sourceAnalysis']}`",
        f"- Decision: `{llm_analysis.get('decision') or 'unknown'}`",
        f"- Classification: `{llm_analysis.get('classification') or 'unknown'}`",
        f"- Root cause: {llm_analysis.get('rootCause') or 'unknown'}",
        "",
        "## Evidence",
        "",
    ]
    lines.extend([f"- {item}" for item in llm_analysis.get("evidence") or []] or ["- No LLM evidence was generated."])

    lines.extend(["", "## RAG Evidence Used By LLM", ""])
    lines.extend(format_rag_evidence(summary.get("ragEvidence") or []))

    lines.extend(["", "## Evidence Trace", ""])
    lines.extend(format_evidence_trace(summary.get("evidenceTrace") or {}))

    lines.extend(["", "## Safety Evaluation", ""])
    lines.extend(format_safety_evaluation(summary.get("safetyEvaluation") or {}))

    if llm_analysis.get("explanationForBeginner"):
        lines.extend(["", "## Beginner Explanation", "", llm_analysis["explanationForBeginner"]])

    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in summary["warnings"]] or ["- none"])
    if llm_analysis:
        lines.extend(["", "## LLM Analysis Output", "", "```json", json.dumps(llm_analysis, indent=2, ensure_ascii=False), "```"])
    lines.extend(["", "## Retrieved Troubleshooting Knowledge", ""])
    lines.extend(format_retrieved_docs(summary["retrievedKnowledge"]))
    analyzer = summary["logAnalyzerResult"]
    lines.extend(
        [
            "",
            "## Tool Result",
            "",
            f"- log_analyzer: `{analyzer['status']}` exitCode=`{analyzer['exitCode']}`",
            f"- command: `{' '.join(analyzer['command'])}`",
            "",
            "## Next Actions",
            "",
        ]
    )
    lines.extend([f"- {item}" for item in llm_analysis.get("recommendedFixes") or []] or ["- Check Ollama local LLM server and model availability."])
    if llm_analysis.get("rerunCommand"):
        lines.append(f"- Recommended re-run: `{llm_analysis['rerunCommand']}`")
    return "\n".join(lines) + "\n"


def format_retrieved_docs(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- No matching knowledge document found."]
    lines = []
    for item in items:
        lines.append(f"- `{item['path']}`: {item['title']} ({', '.join(item['matchedKeywords'])})")
    return lines


def format_timings(timings: dict[str, Any]) -> list[str]:
    if not timings:
        return ["- No timing information was recorded."]
    order = [
        ("ragRetrievalSeconds", "RAG retrieval"),
        ("llmPlanningSeconds", "Initial LLM planning"),
        ("toolValidationSeconds", "Tool validation"),
        ("toolExecutionSeconds", "Tool execution"),
        ("finalLlmEvaluationSeconds", "Final LLM evaluation"),
        ("recoveryPlanningSeconds", "Recovery planning"),
        ("totalSeconds", "Total"),
    ]
    lines = ["| Stage | Seconds |", "|---|---:|"]
    for key, label in order:
        if key in timings:
            lines.append(f"| {label} | {float(timings.get(key) or 0):.3f} |")
    for key, value in timings.items():
        if key not in {item[0] for item in order}:
            try:
                lines.append(f"| {key} | {float(value):.3f} |")
            except (TypeError, ValueError):
                lines.append(f"| {key} | {value} |")
    return lines


def extract_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key) if isinstance(data, dict) else []
    return value if isinstance(value, list) else []


def extract_tool_call_plan(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = data.get("toolCalls") if isinstance(data, dict) else []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def format_rag_evidence(items: list[Any]) -> list[str]:
    if not items:
        return ["- No explicit RAG evidence mapping was generated."]
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        path = item.get("documentPath") or item.get("path") or "unknown"
        title = item.get("title") or "untitled"
        used_for = item.get("usedFor") or item.get("reason") or "not specified"
        evidence_type = item.get("evidenceType") or "unknown"
        lines.append(f"- `{path}`: {title}")
        lines.append(f"  - used for: {used_for}")
        lines.append(f"  - evidence type: `{evidence_type}`")
    return lines


def format_tool_call_plan(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- No supported Tool call plan was generated."]
    lines: list[str] = []
    for item in items:
        tool = item.get("tool") or "unknown"
        mode = item.get("mode") or "unspecified"
        reason = item.get("reason") or "No reason provided."
        lines.append(f"- `{tool}` mode=`{mode}`")
        lines.append(f"  - reason: {reason}")
    return lines


def format_validated_tool_calls(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- No Tool calls were validated."]
    lines: list[str] = []
    for item in items:
        lines.append(
            f"- `{item.get('tool')}` requested=`{item.get('requestedMode')}` effective=`{item.get('effectiveMode')}`"
        )
        if item.get("mutating") and not item.get("executeAllowed"):
            lines.append("  - mutating Tool was forced to dry-run because --execute was not provided.")
    return lines


def format_rejected_tool_calls(items: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        tool = item.get("tool") or "unknown"
        reason = item.get("reason") or "not specified"
        lines.append(f"- `{tool}`: {reason}")
    return lines


def format_safety_evaluation(data: dict[str, Any]) -> list[str]:
    if not data:
        return ["- No safety evaluation was recorded."]
    lines: list[str] = []
    for name, item in data.items():
        if not isinstance(item, dict):
            continue
        status = item.get("status") or "unknown"
        rule = item.get("rule") or ""
        lines.append(f"- `{name}`: `{status}`")
        if rule:
            lines.append(f"  - rule: {rule}")
        if item.get("evidence"):
            lines.append(f"  - evidence: {item.get('evidence')}")
        if item.get("forcedDryRunTools"):
            lines.append(f"  - forced dry-run tools: {', '.join(str(x) for x in item.get('forcedDryRunTools') or [])}")
        if item.get("rejectedCount") not in (None, 0):
            lines.append(f"  - rejected count: {item.get('rejectedCount')}")
    return lines or ["- No safety evaluation entries were recorded."]


def format_evidence_trace(data: dict[str, Any]) -> list[str]:
    if not data:
        return ["- No evidence trace was recorded."]
    lines: list[str] = []
    rag = data.get("ragEvidence") or {}
    if rag:
        lines.append(f"- RAG mode: `{rag.get('retrievalMode') or 'unknown'}`, fallbackUsed=`{rag.get('fallbackUsed')}`")
        selected = rag.get("selectedDocuments") or []
        if selected:
            lines.append("- Selected RAG documents:")
            for item in selected[:5]:
                if not isinstance(item, dict):
                    continue
                lines.append(f"  - `{item.get('path')}` ({item.get('category') or 'unknown'})")
                if item.get("selectionReason"):
                    lines.append(f"    - reason: {item.get('selectionReason')}")
    validation = data.get("toolValidationEvidence") or {}
    if validation:
        lines.append(
            "- Tool validation: "
            f"validated={len(validation.get('validatedToolCalls') or [])}, "
            f"rejected={len(validation.get('rejectedToolCalls') or [])}, "
            f"deferred={len(validation.get('deferredToolCalls') or [])}"
        )
    execution = data.get("executionEvidence") or data.get("toolEvidence") or []
    if execution:
        lines.append("- Execution evidence:")
        for item in execution:
            if not isinstance(item, dict):
                continue
            lines.append(f"  - `{item.get('tool')}` status=`{item.get('status')}` exitCode=`{item.get('exitCode')}`")
    final = data.get("finalJudgmentEvidence") or data.get("llmJudgmentEvidence") or {}
    if final:
        decision = final.get("decision") or final.get("executionDecision") or ""
        classification = final.get("classification") or ""
        if decision or classification:
            lines.append(f"- LLM judgment: decision=`{decision or 'unknown'}` classification=`{classification or 'n/a'}`")
        evidence = final.get("evidence") or []
        if evidence:
            lines.append("- LLM judgment evidence:")
            lines.extend(f"  - {item}" for item in evidence[:8])
    return lines or ["- Evidence trace was empty."]


def raw_from_exception(exc: Exception) -> str:
    return str(getattr(exc, "raw_output", "") or "")


def make_agent_log_dir() -> Path:
    log_dir = Path("logs") / "agent" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def finalize_timings(context: dict[str, Any], execution: dict[str, Any], total_started: float) -> dict[str, Any]:
    timings = dict(context.get("timings") or {})
    timings.update(execution.get("timings") or {})
    timings["totalSeconds"] = elapsed(total_started)
    return timings


if __name__ == "__main__":
    raise SystemExit(main())
