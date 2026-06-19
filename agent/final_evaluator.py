"""Final Tool-result evaluation with a deterministic fallback."""

from __future__ import annotations

from typing import Any, Callable

from agent.llm.client import LLMUnavailable, config_from_env
from agent.llm.planner import (
    LLMOutputParseError,
    evaluate_tool_results_with_llm,
)
from agent.tool_validator import validate_llm_output_schema


def evaluate_final_result(
    context: dict[str, Any],
    planner_result: dict[str, Any],
    execution: dict[str, Any],
    warnings: list[str],
    errors: list[str],
    make_result: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    llm_output = planner_result.get("llmOutput") or {}
    llm_input = compact_final_input(
        context,
        llm_output,
        execution,
        warnings,
        errors,
    )
    config = config_from_env(purpose="final")
    try:
        output, exact_input, raw = evaluate_tool_results_with_llm(
            llm_input["requirementSummary"],
            [],
            [],
            execution["validatedToolCalls"],
            execution["rejectedToolCalls"],
            execution["toolResults"],
            context["generatedFiles"],
            warnings,
            errors,
            config=config,
        )
        validate_llm_output_schema("tool-result-evaluation", output, raw)
        return make_result(True, exact_input, output, raw, config=config)
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        message = str(exc) or "Local LLM final evaluation failed."
        print(f"Final LLM evaluation failed: {message}")
        return make_result(
            False,
            llm_input,
            {},
            str(getattr(exc, "raw_output", "") or ""),
            message,
            config=config,
        )


def compact_final_input(
    context: dict[str, Any],
    llm_output: dict[str, Any],
    execution: dict[str, Any],
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    return {
        "mode": "tool-result-evaluation",
        "requirementSummary": context["requirementSummary"],
        "validatedToolCalls": [
            {
                "tool": item.get("tool"),
                "effectiveMode": item.get("effectiveMode"),
            }
            for item in execution["validatedToolCalls"]
        ],
        "rejectedToolCalls": execution["rejectedToolCalls"],
        "deferredToolCalls": execution.get("deferredToolCalls") or [],
        "toolResults": execution["toolResults"],
        "generatedFiles": context["generatedFiles"],
        "warnings": warnings,
        "errors": errors,
        "plannedStepCount": len(llm_output.get("plannedSteps") or []),
    }
