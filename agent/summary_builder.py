"""Agent requirement summary assembly and user-facing next actions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.context_builder import (
    clarifying_questions,
    extract_list,
    extract_tool_call_plan,
)
from agent.recovery_policy import scrub_failure_context


def build_requirement_summary(
    args: Any,
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
    if planner_result["llmPlannerUsed"] and not execution["validatedToolCalls"]:
        errors.append("LLM output did not include supported toolCalls.")
    if failure_context:
        errors = [
            item
            for item in errors
            if item
            != "Execution failed; recovery plan generated and waiting for user approval."
        ]
    warnings = collect_warnings(tool_results, context)
    if final_result.get("fallbackError"):
        warnings.append(
            "Final LLM evaluation fallback: "
            + str(final_result["fallbackError"])
        )
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
        "skipFinalLlmEvaluation": bool(
            args.skip_final_llm_evaluation or args.run_level == "fast"
        ),
        "executeAllowed": bool(args.execute),
        "kindDeploymentRequested": bool(args.kind_deploy),
        "resumeExisting": bool(args.resume_existing),
        "createdAt": now_iso(),
        "requirementSummary": context["requirementSummary"],
        "intentAnalysis": context["intentAnalysis"],
        "missingInformation": context["missingInformation"],
        "clarifyingQuestions": clarifying_questions(
            context["missingInformation"],
            context["requirementSummary"],
        ),
        "retrievedKnowledge": context["retrievedKnowledge"],
        "retrievalDetails": context.get("retrievalDetails") or {},
        "selectedProfile": context["selectedProfile"],
        "profileCandidates": context["profileCandidates"],
        "profilePolicy": {
            "role": "hint-only",
            "message": (
                "Profiles are optional hints for defaults, examples, and validation rules. "
                "The Agent plans from the current requirement text first."
            ),
        },
        "llmPlan": planner_result.get("llmOutput") or {},
        "llmReasoning": extract_list(
            planner_result.get("llmOutput") or {},
            "reasoning",
        ),
        "ragEvidence": extract_list(
            planner_result.get("llmOutput") or {},
            "ragEvidence",
        ),
        "toolCallPlan": extract_tool_call_plan(
            planner_result.get("llmOutput") or {}
        ),
        "validatedToolCalls": execution["validatedToolCalls"],
        "rejectedToolCalls": execution["rejectedToolCalls"],
        "deferredToolCalls": execution.get("deferredToolCalls") or [],
        "generatedFiles": context["generatedFiles"],
        "toolResults": tool_results,
        "finalLLM": {
            "llmPlannerUsed": final_result.get("llmPlannerUsed"),
            "localLLM": final_result.get("localLLM") or {},
            "error": final_result.get("error") or "",
            "fallbackUsed": bool(final_result.get("fallbackUsed")),
            "fallbackError": final_result.get("fallbackError") or "",
            "output": final_result.get("llmOutput") or {},
        },
        "failureContext": (
            scrub_failure_context(failure_context) if failure_context else {}
        ),
        "recovery": recovery_summary(recovery_result, failure_context),
        "warnings": warnings,
        "errors": errors,
        "nextRecommendedActions": next_actions(
            context,
            tool_results,
            planner_result,
            final_result,
        ),
    }


def recovery_summary(
    recovery_result: dict[str, Any] | None,
    failure_context: dict[str, Any] | None,
) -> dict[str, Any]:
    recovery = recovery_result or {}
    return {
        "waitingForUserApproval": bool(failure_context),
        "llmPlannerUsed": recovery.get("llmPlannerUsed"),
        "localLLM": recovery.get("localLLM") or {},
        "error": recovery.get("error") or "",
        "rawPlan": recovery.get("rawRecoveryPlan") or {},
        "plan": recovery.get("llmOutput") or {},
        "policyEvaluation": recovery.get("policyEvaluation") or {},
        "rejectedRecoveryToolCalls": recovery.get("rejectedRecoveryToolCalls")
        or [],
        "retrievedTroubleshootingDocs": recovery.get(
            "retrievedTroubleshootingDocs"
        )
        or [],
        "retrievalDetails": recovery.get("retrievalDetails") or {},
    }


def collect_warnings(
    tool_results: list[dict[str, Any]],
    context: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if context["missingInformation"]:
        warnings.append(
            "Requirement has missing or weakly inferred information: "
            + ", ".join(context["missingInformation"])
        )
    for result in tool_results:
        if "Warnings:" in result.get("stdout", ""):
            warnings.append(f"{result['tool']} reported warnings.")
    return warnings


def collect_errors(tool_results: list[dict[str, Any]]) -> list[str]:
    return [
        f"{result['tool']} failed with exit code {result['exitCode']}"
        for result in tool_results
        if result["exitCode"] != 0
    ]


def next_actions(
    context: dict[str, Any],
    tool_results: list[dict[str, Any]],
    planner_result: dict[str, Any],
    final_result: dict[str, Any] | None = None,
) -> list[str]:
    final_actions = (
        ((final_result or {}).get("llmOutput") or {}).get(
            "recommendedNextActions"
        )
        or []
    )
    if final_actions:
        return [str(item) for item in final_actions if item]
    llm_actions = (planner_result.get("llmOutput") or {}).get("nextActions") or []
    actions = [str(item) for item in llm_actions if item]
    if any(result["exitCode"] != 0 for result in tool_results):
        actions.insert(
            0,
            "실패한 Tool의 stderr와 생성된 summary를 먼저 확인합니다.",
        )
    if planner_result["error"]:
        actions.append("Ollama local LLM 서버와 모델 상태를 확인합니다.")
    if not actions:
        actions = [
            f"검토: {context['generatedFiles']['commandPlan']}",
            (
                "scaffold preflight: python3 agent/tools/scaffold_runner.py "
                f"--input {context['generatedFiles']['operatorSpec']} "
                f"--workspace {context['workspace']} --preflight"
            ),
        ]
    return actions


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
