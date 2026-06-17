#!/usr/bin/env python3
"""LLM-based Agent orchestrator for the Kubebuilder automation MVP."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llm.client import LLMUnavailable, config_from_env  # noqa: E402
from agent.llm.planner import (  # noqa: E402
    LLMOutputParseError,
    analyze_log_with_llm,
    evaluate_tool_results_with_llm,
    plan_recovery_with_llm,
    plan_requirement_with_llm,
)
from agent.rag.retriever import search_detailed as retrieve_knowledge_detailed  # noqa: E402
from agent.tools import langchain_wrappers as tools  # noqa: E402


RECOVERY_TOOL_ALLOWLIST = {
    "requirement_editor",
    "spec_generator",
    "command_planner",
    "scaffold_runner",
    "artifact_patcher",
    "validation",
    "log_analyzer",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LLM-based Kubebuilder Agent orchestrator.")
    parser.add_argument("--requirement", help="Natural language requirement file.")
    parser.add_argument("--log-dir", help="Existing logs/scaffold, logs/patch, or logs/e2e directory to analyze.")
    parser.add_argument("--analyze-log", help="Alias of --log-dir.")
    parser.add_argument("--profile", help="Profile YAML path.")
    parser.add_argument("--planner", default="llm", choices=["llm"], help="Only the LLM planner is supported.")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "execute"], help="Agent mode. Defaults to dry-run.")
    parser.add_argument("--workspace", default="workspace/generated-operators", help="Scaffold workspace parent.")
    parser.add_argument("--execute", action="store_true", help="Allow real execution for mutating tools.")
    args = parser.parse_args()

    if args.analyze_log and not args.log_dir:
        args.log_dir = args.analyze_log
    if args.log_dir:
        return run_log_analysis_agent(args)
    if not args.requirement:
        raise SystemExit("--requirement is required unless --log-dir or --analyze-log is provided.")
    return run_requirement_agent(args)


def run_requirement_agent(args: argparse.Namespace) -> int:
    requirement_path = Path(args.requirement)
    requirement_text = requirement_path.read_text(encoding="utf-8")
    profile = load_profile(Path(args.profile)) if args.profile else {}
    context = build_requirement_context(requirement_path, requirement_text, args.profile, profile, args.workspace)
    log_dir = make_agent_log_dir()

    print("LLM Agent Orchestrator")
    print(f"Requirement: {context['requirement']}")
    print(f"Selected profile: {context['selectedProfile'].get('path') or '<none>'}")
    print("Default safety mode: dry-run")

    planner_result = call_requirement_planner(args, requirement_text, context)
    if planner_result["error"]:
        execution = {"validatedToolCalls": [], "rejectedToolCalls": [], "deferredToolCalls": [], "toolResults": []}
        final_result = empty_final_result(planner_result["error"])
        summary = build_requirement_summary(args, context, planner_result, execution, final_result)
        write_agent_artifacts(log_dir, summary, planner_result, context["retrievedKnowledge"], execution, final_result)
        report = render_requirement_report(summary)
        (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
        print(report)
        print(f"\nAgent logs: {log_dir}")
        return 2

    execution = execute_planned_tools(context, args.mode, args.execute, planner_result)
    initial_errors = collect_errors(execution["toolResults"])
    if planner_result["error"]:
        initial_errors.append(planner_result["error"])
    recovery_result = None
    failure_context = detect_failure_context(context, planner_result, execution, args)
    if failure_context:
        recovery_result = call_recovery_planner(context, planner_result, execution, failure_context, args)
        final_result = empty_final_result("Execution failed; recovery plan generated and waiting for user approval.")
    else:
        final_result = call_final_evaluator(context, planner_result, execution, collect_warnings(execution["toolResults"], context), initial_errors)
    summary = build_requirement_summary(args, context, planner_result, execution, final_result, recovery_result, failure_context)
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
        "safetyMode": args.mode,
    }
    try:
        output, exact_input, raw = plan_requirement_with_llm(
            requirement_text,
            context["retrievedKnowledge"],
            context["selectedProfile"],
            args.mode,
        )
        return llm_result(True, exact_input, output, raw)
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM planner failed."
        print(f"LLM planner failed: {message}")
        return llm_result(False, llm_input, {}, raw_from_exception(exc), message)


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


def build_requirement_context(
    requirement_path: Path,
    requirement_text: str,
    profile_path: str | None,
    profile: dict[str, Any],
    workspace: str,
) -> dict[str, Any]:
    summary = summarize_requirement(requirement_text)
    kind = summary.get("kind") or "operator"
    kind_slug = kind.lower()
    retrieval = perform_retrieval(requirement_text, limit=3, purpose="requirement")
    retrieved = retrieval["selectedContext"]
    return {
        "requirement": str(requirement_path),
        "requirementSummary": summary,
        "missingInformation": missing_information(summary, requirement_text),
        "retrievedKnowledge": retrieved,
        "retrievalDetails": retrieval,
        "selectedProfile": {
            "path": profile_path or "",
            "name": profile.get("profileName", ""),
            "description": profile.get("description", ""),
            "managedResources": profile.get("managedResources") or [],
        },
        "workspace": workspace,
        "targetProjectDir": str(Path(workspace) / infer_project_name(kind, f"generated/{kind_slug}-operator-spec.yaml")),
        "generatedFiles": {
            "operatorSpec": f"generated/{kind_slug}-operator-spec.yaml",
            "commandPlan": f"generated/{kind_slug}-command-plan.md",
        },
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


def execute_planned_tools(
    context: dict[str, Any],
    mode: str,
    allow_execute: bool,
    planner_result: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    generated = context["generatedFiles"]
    mutating_execute = mode == "execute" and allow_execute
    supported_calls = {
        "spec_generator": {
            "mutating": False,
            "requiredArgs": ["requirement", "output"],
            "arguments": {"requirement": context["requirement"], "output": generated["operatorSpec"]},
            "call": lambda: tools.spec_generator(context["requirement"], generated["operatorSpec"]),
        },
        "command_planner": {
            "mutating": False,
            "requiredArgs": ["input", "output", "workspace"],
            "arguments": {"input": generated["operatorSpec"], "output": generated["commandPlan"], "workspace": context["workspace"]},
            "call": lambda: tools.command_planner(generated["operatorSpec"], generated["commandPlan"], context["workspace"]),
        },
        "scaffold_runner": {
            "mutating": True,
            "requiredArgs": ["input", "workspace"],
            "arguments": {
                "input": generated["operatorSpec"],
                "workspace": context["workspace"],
                "execute": mutating_execute,
            },
            "call": lambda: tools.scaffold_runner(generated["operatorSpec"], context["workspace"], execute=mutating_execute),
        },
        "artifact_patcher": {
            "mutating": True,
            "requiredArgs": ["input", "project"],
            "arguments": {
                "input": generated["operatorSpec"],
                "project": context["targetProjectDir"],
                "profile": context["selectedProfile"].get("path"),
                "execute": mutating_execute,
            },
            "call": lambda: tools.artifact_patcher(
                generated["operatorSpec"],
                context["targetProjectDir"],
                context["selectedProfile"].get("path"),
                execute=mutating_execute,
            ),
        },
        "validation": {
            "mutating": False,
            "requiredArgs": ["project"],
            "arguments": {
                "project": context["targetProjectDir"],
                "targets": ["generate", "manifests", "test"],
            },
            "call": lambda: tools.validation(context["targetProjectDir"], ["generate", "manifests", "test"]),
        },
        "e2e_runner": {
            "mutating": True,
            "requiredArgs": ["input"],
            "arguments": {
                "input": generated["operatorSpec"],
                "profile": context["selectedProfile"].get("path"),
                "execute": mutating_execute,
            },
            "call": lambda: tools.e2e_runner(generated["operatorSpec"], context["selectedProfile"].get("path"), execute=mutating_execute),
        },
    }
    validated, rejected, deferred = validate_planned_tool_calls(planner_result, supported_calls, mode, allow_execute)
    if not validated:
        print("\nLLM planner did not request any supported Tool calls.")
        return {"validatedToolCalls": [], "rejectedToolCalls": rejected, "deferredToolCalls": deferred, "toolResults": []}

    results: list[dict[str, Any]] = []
    for item in validated:
        name = item["tool"]
        call = supported_calls[name]["call"]
        print(f"\nCalling tool: {name}")
        result = call()
        result["tool"] = name
        results.append(result)
        print(f"exitCode={result['exitCode']} status={result['status']}")
        if result["exitCode"] != 0:
            break
    return {"validatedToolCalls": validated, "rejectedToolCalls": rejected, "deferredToolCalls": deferred, "toolResults": results}


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
            failed_step = failed_validation_step(result)
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


def scrub_failure_context(context: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in context.items() if key != "failedResult"}


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


def validate_recovery_plan(raw_plan: dict[str, Any], failure_context: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    unsupported = detect_unsupported_field_types(context)
    classification = policy_classification(raw_plan, failure_context, unsupported)
    rejected = validate_raw_recovery_calls(raw_plan, classification)

    if classification == "invalid-field-type" and unsupported:
        field = unsupported[0]
        evidence_refs = [
            f"operatorSpec:{field['section']}.{field['name']}",
            f"failedTool:{failure_context.get('failedTool')}",
            f"failedStep:{failure_context.get('failedStep')}",
        ]
        validated_calls = [
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
        root_cause = raw_plan.get("rootCause") or failure_context.get("stderrTail") or "Recovery requires manual review."
        proposed = raw_plan.get("proposedFixes") if isinstance(raw_plan.get("proposedFixes"), list) else ["Review failure-context.json and approve the smallest safe recovery step."]
        rerun_from = str(failure_context.get("failedTool") or "failed step")

    validated_plan = {
        "decision": "manual-review-required" if classification in {"unknown", "image-pull"} else "recovery-required",
        "classification": classification,
        "rootCause": root_cause,
        "evidence": raw_plan.get("evidence") if isinstance(raw_plan.get("evidence"), list) else default_recovery_evidence(failure_context, unsupported),
        "proposedFixes": proposed,
        "validatedRecoveryToolCalls": validated_calls,
        "rejectedRecoveryToolCalls": rejected,
        "rerunFromStep": rerun_from,
        "risks": raw_plan.get("risks") if isinstance(raw_plan.get("risks"), list) else ["Recovery calls require user approval before execution."],
        "beginnerSummary": raw_plan.get("beginnerSummary") or "Agent validated the LLM recovery proposal against local policy and is waiting for user approval.",
        "status": "waiting-for-user-approval",
    }
    return {
        "validatedRecoveryPlan": validated_plan,
        "rejectedRecoveryToolCalls": rejected,
        "policyEvaluation": {
            "classification": classification,
            "unsupportedFieldTypes": unsupported,
            "allowlist": sorted(RECOVERY_TOOL_ALLOWLIST),
            "rawRecoveryToolCalls": raw_plan.get("recoveryToolCalls") or [],
            "validatedRecoveryToolCalls": validated_calls,
            "rejectedRecoveryToolCalls": rejected,
            "status": "waiting-for-user-approval",
        },
    }


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


def policy_classification(raw_plan: dict[str, Any], failure_context: dict[str, Any], unsupported: list[dict[str, str]]) -> str:
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
        normalized = normalize_tool_name(tool)
        if normalized not in RECOVERY_TOOL_ALLOWLIST:
            rejected.append({"tool": tool, "reason": rejected_recovery_reason(tool, classification)})
    return rejected


def rejected_recovery_reason(tool: str, classification: str) -> str:
    if tool == "controller-gen" and classification == "invalid-field-type":
        return "Not in recovery allowlist and rerunning alone does not correct the invalid field type."
    if tool == "go_version_checker" and classification == "invalid-field-type":
        return "No evidence that the Go version caused this failure."
    return "Not in recovery allowlist."


def generic_validated_recovery_calls(classification: str, failure_context: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_refs = [f"failedTool:{failure_context.get('failedTool')}", f"failedStep:{failure_context.get('failedStep')}"]
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
    return []


def default_recovery_evidence(failure_context: dict[str, Any], unsupported: list[dict[str, str]]) -> list[str]:
    evidence = []
    if unsupported:
        evidence.extend(f"{item['section']}.{item['name']} type={item['type']}" for item in unsupported)
    if failure_context.get("failedTool"):
        evidence.append(f"failedTool={failure_context.get('failedTool')}")
    if failure_context.get("failedStep"):
        evidence.append(f"failedStep={failure_context.get('failedStep')}")
    if failure_context.get("exitCode") is not None:
        evidence.append(f"exitCode={failure_context.get('exitCode')}")
    return evidence


def validate_planned_tool_calls(
    planner_result: dict[str, Any],
    supported_calls: dict[str, Any],
    mode: str,
    allow_execute: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    output = planner_result.get("llmOutput") or {}
    requested = output.get("toolCalls") if isinstance(output, dict) else None
    if not isinstance(requested, list):
        return [], [{"tool": "", "reason": "LLM output did not include a toolCalls list.", "raw": requested}], []

    validated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in requested:
        if not isinstance(item, dict):
            rejected.append({"tool": "", "reason": "Tool call is not a JSON object.", "raw": item})
            continue
        tool_name = normalize_tool_name(str(item.get("tool") or ""))
        requested_mode = normalize_tool_mode(str(item.get("mode") or "dry-run"), mode)
        if tool_name not in supported_calls:
            rejected.append({"tool": tool_name, "reason": "Tool is not in the Agent allowlist.", "raw": item})
            continue
        if mode == "dry-run" and tool_name in {"artifact_patcher", "validation"}:
            deferred.append(
                {
                    "tool": tool_name,
                    "reason": "Deferred in Agent dry-run because this Tool requires a scaffolded project directory.",
                    "raw": item,
                }
            )
            continue
        if tool_name in seen:
            rejected.append({"tool": tool_name, "reason": "Duplicate Tool call was skipped.", "raw": item})
            continue
        if requested_mode not in {"generate", "dry-run", "execute"}:
            rejected.append({"tool": tool_name, "reason": f"Unsupported mode: {requested_mode}", "raw": item})
            continue
        seen.add(tool_name)
        spec = supported_calls[tool_name]
        arguments = dict(spec["arguments"])
        missing = [name for name in spec["requiredArgs"] if arguments.get(name) in (None, "")]
        if missing:
            rejected.append({"tool": tool_name, "reason": "Missing required arguments: " + ", ".join(missing), "raw": item})
            continue
        path_error = validate_tool_paths(tool_name, arguments)
        if path_error:
            rejected.append({"tool": tool_name, "reason": path_error, "raw": item})
            continue
        effective_mode = "execute" if spec["mutating"] and mode == "execute" and allow_execute else requested_mode
        if spec["mutating"] and not allow_execute:
            effective_mode = "dry-run"
        validated.append(
            {
                "tool": tool_name,
                "requestedMode": requested_mode,
                "effectiveMode": effective_mode,
                "reason": item.get("reason") or "",
                "arguments": arguments,
                "mutating": bool(spec["mutating"]),
                "executeAllowed": bool(allow_execute),
            }
        )
    return validated, rejected, deferred


def planned_tool_calls(
    planner_result: dict[str, Any],
    supported_calls: dict[str, Any],
) -> list[tuple[str, Any]]:
    validated, _, _ = validate_planned_tool_calls(planner_result, supported_calls, "dry-run", False)
    return [(item["tool"], supported_calls[item["tool"]]) for item in validated]


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
        "agentMode": args.mode,
        "executeAllowed": bool(args.execute),
        "createdAt": now_iso(),
        "requirementSummary": context["requirementSummary"],
        "missingInformation": context["missingInformation"],
        "retrievedKnowledge": context["retrievedKnowledge"],
        "retrievalDetails": context.get("retrievalDetails") or {},
        "selectedProfile": context["selectedProfile"],
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


def normalize_tool_name(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "scaffold": "scaffold_runner",
        "scaffold_runner_dry_run": "scaffold_runner",
        "patch": "artifact_patcher",
        "artifact_patch": "artifact_patcher",
        "validate": "validation",
        "make": "validation",
        "make_generate": "validation",
        "make_manifests": "validation",
        "make_test": "validation",
    }
    return aliases.get(normalized, normalized)


def normalize_tool_mode(value: str, agent_mode: str) -> str:
    normalized = value.strip().lower()
    if "|" in normalized:
        options = {part.strip() for part in normalized.split("|")}
        if agent_mode == "execute" and "execute" in options:
            return "execute"
        if "dry-run" in options:
            return "dry-run"
    aliases = {
        "dry_run": "dry-run",
        "dryrun": "dry-run",
        "plan": "dry-run",
        "generate": "generate",
        "execute": "execute",
    }
    return aliases.get(normalized, normalized)


def validate_tool_paths(tool_name: str, arguments: dict[str, Any]) -> str:
    path_keys = ["workspace", "project"]
    for key in path_keys:
        value = arguments.get(key)
        if value and not is_inside_repo(Path(str(value))):
            return f"{key} path is outside the project root: {value}"
    if tool_name == "validation":
        targets = arguments.get("targets") or []
        invalid = [target for target in targets if target not in {"generate", "manifests", "test"}]
        if invalid:
            return "Unsupported validation targets: " + ", ".join(str(item) for item in invalid)
    return ""


def is_inside_repo(path: Path) -> bool:
    resolved = (Path.cwd() / path).resolve() if not path.is_absolute() else path.resolve()
    root = Path.cwd().resolve()
    try:
        resolved.relative_to(root)
        return True
    except ValueError:
        return False


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
        "## Missing Information Check",
        "",
        *([f"- {item}" for item in summary["missingInformation"]] or ["- No critical missing information found."]),
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

    profile = summary["selectedProfile"]
    lines.extend(
        [
            "",
            "## Selected Profile",
            "",
            f"- Path: `{profile.get('path') or 'none'}`",
            f"- Name: `{profile.get('name') or 'none'}`",
            f"- Managed resources: `{', '.join(profile.get('managedResources') or []) or 'none'}`",
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


def write_agent_artifacts(
    log_dir: Path,
    summary: dict[str, Any],
    planner_result: dict[str, Any],
    retrieved_docs: list[dict[str, Any]],
    execution_or_results: dict[str, list[dict[str, Any]]] | list[dict[str, Any]],
    final_result: dict[str, Any] | None = None,
    recovery_result: dict[str, Any] | None = None,
) -> None:
    if isinstance(execution_or_results, dict):
        execution = execution_or_results
        tool_results = execution.get("toolResults") or []
    else:
        execution = {"validatedToolCalls": [], "rejectedToolCalls": [], "toolResults": execution_or_results}
        tool_results = execution_or_results

    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (log_dir / "initial-plan.json").write_text(json.dumps(planner_result.get("llmOutput") or {}, indent=2, ensure_ascii=False), encoding="utf-8")
    (log_dir / "validated-tool-calls.json").write_text(
        json.dumps(execution.get("validatedToolCalls") or [], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (log_dir / "rejected-tool-calls.json").write_text(
        json.dumps(execution.get("rejectedToolCalls") or [], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (log_dir / "deferred-tool-calls.json").write_text(
        json.dumps(execution.get("deferredToolCalls") or [], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (log_dir / "llm-input.json").write_text(json.dumps(planner_result.get("llmInput") or {}, indent=2, ensure_ascii=False), encoding="utf-8")
    (log_dir / "llm-output.json").write_text(
        json.dumps(
            {
                "planner": "llm",
                "localLLM": planner_result.get("localLLM"),
                "llmPlannerUsed": planner_result.get("llmPlannerUsed"),
                "error": planner_result.get("error"),
                "output": planner_result.get("llmOutput") or {},
                "rawOutput": planner_result.get("rawOutput") or "",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (log_dir / "retrieved-docs.json").write_text(json.dumps(retrieved_docs, indent=2, ensure_ascii=False), encoding="utf-8")
    retrieval = summary.get("retrievalDetails") or {}
    if retrieval:
        (log_dir / "retrieval-query.json").write_text(
            json.dumps(retrieval.get("retrievalQuery") or {}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "vector-results.json").write_text(
            json.dumps(retrieval.get("vectorSearchResults") or [], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "keyword-results.json").write_text(
            json.dumps(retrieval.get("keywordSearchResults") or [], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "hybrid-results.json").write_text(
            json.dumps(retrieval.get("hybridResults") or [], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "reranker-input.json").write_text(
            json.dumps((retrieval.get("rerankerOutput") or {}).get("allRankedResults") or [], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "reranker-output.json").write_text(
            json.dumps(retrieval.get("rerankerOutput") or {}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "selected-context.json").write_text(
            json.dumps(retrieval.get("selectedContext") or [], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    (log_dir / "tool-results.json").write_text(json.dumps(tool_results, indent=2, ensure_ascii=False), encoding="utf-8")
    write_tool_output_logs(log_dir, tool_results)
    (log_dir / "llm-raw-output.txt").write_text(planner_result.get("rawOutput") or "", encoding="utf-8")
    if final_result is not None:
        (log_dir / "final-llm-input.json").write_text(
            json.dumps(final_result.get("llmInput") or {}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "final-llm-output.json").write_text(
            json.dumps(
                {
                    "planner": "llm",
                    "localLLM": final_result.get("localLLM"),
                    "llmPlannerUsed": final_result.get("llmPlannerUsed"),
                    "error": final_result.get("error"),
                    "output": final_result.get("llmOutput") or {},
                    "rawOutput": final_result.get("rawOutput") or "",
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    recovery = summary.get("recovery") or {}
    failure_context = summary.get("failureContext") or {}
    if failure_context or recovery_result is not None:
        (log_dir / "failure-context.json").write_text(json.dumps(failure_context, indent=2, ensure_ascii=False), encoding="utf-8")
        (log_dir / "retrieved-troubleshooting-docs.json").write_text(
            json.dumps(recovery.get("retrievedTroubleshootingDocs") or [], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        recovery_retrieval = recovery.get("retrievalDetails") or {}
        if recovery_retrieval:
            (log_dir / "recovery-retrieval-details.json").write_text(
                json.dumps(recovery_retrieval, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        (log_dir / "raw-recovery-plan.json").write_text(
            json.dumps(recovery.get("rawPlan") or {}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "recovery-llm-input.json").write_text(
            json.dumps((recovery_result or {}).get("llmInput") or {}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "recovery-llm-raw-output.txt").write_text((recovery_result or {}).get("rawOutput") or "", encoding="utf-8")
        (log_dir / "recovery-plan.json").write_text(
            json.dumps(recovery.get("plan") or {}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "validated-recovery-plan.json").write_text(
            json.dumps(recovery.get("plan") or {}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "rejected-recovery-tool-calls.json").write_text(
            json.dumps(recovery.get("rejectedRecoveryToolCalls") or [], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        (log_dir / "recovery-policy-evaluation.json").write_text(
            json.dumps(recovery.get("policyEvaluation") or {}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def write_tool_output_logs(log_dir: Path, tool_results: list[dict[str, Any]]) -> None:
    for index, result in enumerate(tool_results, start=1):
        tool = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(result.get("tool") or f"tool-{index}")).strip("-")
        prefix = f"{index:02d}-{tool}"
        (log_dir / f"{prefix}.stdout.log").write_text(str(result.get("stdout") or ""), encoding="utf-8")
        (log_dir / f"{prefix}.stderr.log").write_text(str(result.get("stderr") or ""), encoding="utf-8")
        for step_index, step in enumerate(result.get("steps") or [], start=1):
            target = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(step.get("target") or step_index)).strip("-")
            (log_dir / f"{prefix}-{step_index:02d}-{target}.stdout.log").write_text(
                str(step.get("stdout") or ""),
                encoding="utf-8",
            )
            (log_dir / f"{prefix}-{step_index:02d}-{target}.stderr.log").write_text(
                str(step.get("stderr") or ""),
                encoding="utf-8",
            )


def raw_from_exception(exc: Exception) -> str:
    return str(getattr(exc, "raw_output", "") or "")


def make_agent_log_dir() -> Path:
    log_dir = Path("logs") / "agent" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
