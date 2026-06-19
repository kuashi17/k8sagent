#!/usr/bin/env python3
"""LLM-based Agent orchestrator for the Kubebuilder automation MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
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
from agent.execution_engine import execute_planned_tools  # noqa: E402
from agent.evidence_builder import (  # noqa: E402
    build_log_analysis_evidence_trace,
    build_log_analysis_safety_evaluation,
    build_requirement_evidence_trace,
    build_requirement_safety_evaluation,
)
from agent.failure_context import build_failure_rag_query, detect_failure_context  # noqa: E402
from agent.llm.planner import (  # noqa: E402
    LLMOutputParseError,
    analyze_log_with_llm,
    evaluate_tool_results_with_llm,
    plan_recovery_with_llm,
    plan_requirement_with_llm,
)
from agent.recovery_policy import (  # noqa: E402
    deterministic_recovery_classification,
    scrub_failure_context,
    validate_recovery_plan,
)
from agent.retrieval_context import (  # noqa: E402
    build_log_rag_query,
    perform_retrieval,
    requirement_rag_limit,
)
from agent.report_writer import write_agent_artifacts  # noqa: E402
from agent import report_renderer  # noqa: E402
from agent.summary_builder import (  # noqa: E402
    build_requirement_summary,
    collect_errors,
    collect_warnings,
)
from agent.context_builder import (  # noqa: E402
    build_requirement_context as assemble_requirement_context,
    clarifying_questions,
    extract_list,
    extract_tool_call_plan,
)
from agent.tool_validator import normalize_tool_name, validate_llm_output_schema, validate_planned_tool_calls  # noqa: E402
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
    context = assemble_requirement_context(
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
        report = report_renderer.render_requirement_report(summary)
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
    failure_context = detect_failure_context(context, execution, args.mode)
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
    report = report_renderer.render_requirement_report(summary)
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
    (log_dir / "agent-report.md").write_text(report_renderer.render_requirement_report(summary), encoding="utf-8")


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
    report = report_renderer.render_log_analysis_report(summary)
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



def load_profile(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"profile YAML must be a mapping: {path}")
    data["_profilePath"] = str(path)
    return data



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
