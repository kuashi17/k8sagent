"""Recovery planning orchestration around deterministic policy and Local LLM."""

from __future__ import annotations

from typing import Any, Callable

from agent.failure_context import build_failure_rag_query
from agent.llm.client import LLMUnavailable, config_from_env
from agent.llm.planner import LLMOutputParseError, plan_recovery_with_llm
from agent.recovery_policy import (
    deterministic_recovery_classification,
    scrub_failure_context,
    validate_recovery_plan,
)
from agent.retrieval_context import perform_retrieval
from agent.tool_validator import validate_llm_output_schema


def plan_recovery(
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
    failure_context: dict[str, Any],
    agent_mode: str,
    extract_tool_plan: Callable[[dict[str, Any]], list[dict[str, Any]]],
    make_result: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    deterministic_classification = deterministic_recovery_classification(
        failure_context
    )
    if deterministic_classification:
        return deterministic_result(
            context,
            failure_context,
            deterministic_classification,
        )

    query = build_failure_rag_query(failure_context)
    retrieval = perform_retrieval(query, limit=3, purpose="recovery")
    retrieved = retrieval["selectedContext"]
    successful = [
        item
        for item in execution["toolResults"]
        if item.get("exitCode") == 0
    ]
    failed = failure_context.get("failedResult") or {}
    tool_plan = extract_tool_plan(planner_result.get("llmOutput") or {})
    scrubbed = scrub_failure_context(failure_context)
    llm_input = {
        "mode": "recovery-planning",
        "requirementSummary": context["requirementSummary"],
        "toolPlan": tool_plan,
        "successfulToolResults": successful,
        "failedToolResult": failed,
        "failureContext": scrubbed,
        "retrievedDocs": retrieved,
        "agentMode": agent_mode,
    }
    config = config_from_env(purpose="recovery")
    try:
        output, exact_input, raw = plan_recovery_with_llm(
            context["requirementSummary"],
            tool_plan,
            successful,
            failed,
            scrubbed,
            retrieved,
            agent_mode,
            config=config,
        )
        validate_llm_output_schema("recovery-planning", output, raw)
        result = make_result(
            True,
            exact_input,
            output,
            raw,
            config=config,
        )
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM recovery planning failed."
        print(f"Recovery LLM planning failed: {message}")
        result = make_result(
            False,
            llm_input,
            {},
            str(getattr(exc, "raw_output", "") or ""),
            message,
            config=config,
        )
        output = {}
    policy = validate_recovery_plan(output, scrubbed, context)
    result.update(
        {
            "rawRecoveryPlan": output,
            "llmOutput": policy["validatedRecoveryPlan"],
            "policyEvaluation": policy["policyEvaluation"],
            "rejectedRecoveryToolCalls": policy[
                "rejectedRecoveryToolCalls"
            ],
            "retrievedTroubleshootingDocs": retrieved,
            "retrievalDetails": retrieval,
        }
    )
    return result


def deterministic_result(
    context: dict[str, Any],
    failure_context: dict[str, Any],
    classification: str,
) -> dict[str, Any]:
    scrubbed = scrub_failure_context(failure_context)
    policy = validate_recovery_plan(
        {"classification": classification},
        scrubbed,
        context,
    )
    cfg = config_from_env(purpose="recovery")
    return {
        "requestedPlanner": "policy",
        "effectivePlanner": "deterministic-recovery-policy",
        "llmPlannerUsed": False,
        "localLLM": {
            "baseUrl": cfg.base_url,
            "model": cfg.model,
            "timeoutSeconds": cfg.timeout_seconds,
        },
        "llmInput": {
            "mode": "recovery-planning",
            "skipped": True,
            "reason": f"Deterministic recovery classification: {classification}",
            "failureContext": scrubbed,
        },
        "llmOutput": policy["validatedRecoveryPlan"],
        "rawOutput": "",
        "error": "",
        "skipped": True,
        "skipReason": classification,
        "rawRecoveryPlan": {},
        "policyEvaluation": policy["policyEvaluation"],
        "rejectedRecoveryToolCalls": policy["rejectedRecoveryToolCalls"],
        "retrievedTroubleshootingDocs": [],
        "retrievalDetails": {},
    }
