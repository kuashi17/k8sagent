"""Shared runtime helpers for Agent orchestration entry points."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from agent.llm.client import config_from_env


def llm_result(
    used: bool,
    llm_input: dict[str, Any],
    output: dict[str, Any],
    raw: str,
    error: str = "",
    *,
    config: Any | None = None,
) -> dict[str, Any]:
    cfg = config or config_from_env()
    return {
        "requestedPlanner": "llm",
        "effectivePlanner": "llm" if used else "none",
        "llmPlannerUsed": used,
        "localLLM": {
            "baseUrl": cfg.base_url,
            "model": cfg.model,
            "timeoutSeconds": cfg.timeout_seconds,
            "maxTokens": cfg.max_tokens,
        },
        "llmInput": llm_input,
        "llmOutput": output,
        "rawOutput": raw,
        "error": error,
    }


def empty_final_result(error: str) -> dict[str, Any]:
    cfg = config_from_env(purpose="final")
    return {
        "requestedPlanner": "llm",
        "effectivePlanner": "none",
        "llmPlannerUsed": False,
        "localLLM": {
            "baseUrl": cfg.base_url,
            "model": cfg.model,
            "timeoutSeconds": cfg.timeout_seconds,
            "maxTokens": cfg.max_tokens,
        },
        "llmInput": {},
        "llmOutput": {},
        "rawOutput": "",
        "error": error,
    }


def should_skip_final_llm_evaluation(args: Any) -> bool:
    return bool(
        args.skip_final_llm_evaluation or args.run_level == "fast"
    )


def rule_based_final_result(
    context: dict[str, Any],
    execution: dict[str, Any],
    warnings: list[str],
    errors: list[str],
    args: Any,
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
        "completedSteps": [
            str(item.get("tool"))
            for item in tool_results
            if item.get("exitCode") == 0
        ],
        "failedSteps": [str(item.get("tool")) for item in failed],
        "generatedArtifacts": [
            path for path in context.get("generatedFiles", {}).values()
        ],
        "validationResults": validation_results_from_tool_results(
            tool_results
        ),
        "evidence": [
            (
                f"{item.get('tool')} exitCode={item.get('exitCode')} "
                f"status={item.get('status')}"
            )
            for item in tool_results
        ],
        "warnings": warnings
        + (
            ["Final LLM evaluation skipped by fast mode."]
            if args.run_level == "fast"
            else []
        ),
        "recommendedNextActions": [
            "Review validated Tool calls and generated artifacts.",
            "Use execute mode only after reviewing safety-evaluation.json.",
        ],
        "beginnerSummary": (
            "A deterministic summary was built from validated Tool exit codes."
        ),
    }
    cfg = config_from_env(purpose="final")
    return {
        "requestedPlanner": "llm",
        "effectivePlanner": "rule-based-fast-summary",
        "llmPlannerUsed": False,
        "localLLM": {
            "baseUrl": cfg.base_url,
            "model": cfg.model,
            "timeoutSeconds": cfg.timeout_seconds,
            "maxTokens": cfg.max_tokens,
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
        "skipReason": (
            "fast mode"
            if args.run_level == "fast"
            else "--skip-final-llm-evaluation"
        ),
    }


def fallback_final_result(
    context: dict[str, Any],
    execution: dict[str, Any],
    warnings: list[str],
    errors: list[str],
    args: Any,
    failed_result: dict[str, Any],
) -> dict[str, Any]:
    fallback_error = str(
        failed_result.get("error") or "Final LLM evaluation failed."
    )
    result = rule_based_final_result(
        context,
        execution,
        warnings + [f"Final LLM evaluation fallback: {fallback_error}"],
        errors,
        args,
    )
    result.update(
        {
            "effectivePlanner": "rule-based-final-fallback",
            "llmInput": failed_result.get("llmInput") or {},
            "rawOutput": failed_result.get("rawOutput") or "",
            "fallbackUsed": True,
            "fallbackError": fallback_error,
            "skipped": False,
            "skipReason": "",
        }
    )
    result["llmOutput"]["beginnerSummary"] = (
        "Tool execution succeeded, but final LLM evaluation failed. "
        "A deterministic Tool-result summary was used."
    )
    return result


def validation_results_from_tool_results(
    tool_results: list[dict[str, Any]],
) -> dict[str, str]:
    results = {
        "makeGenerate": "skipped",
        "makeManifests": "skipped",
        "makeTest": "skipped",
    }
    for item in tool_results:
        if item.get("tool") != "validation":
            continue
        for step in item.get("steps") or []:
            target = step.get("target")
            status = (
                "succeeded" if step.get("exitCode") == 0 else "failed"
            )
            if target == "generate":
                results["makeGenerate"] = status
            elif target == "manifests":
                results["makeManifests"] = status
            elif target == "test":
                results["makeTest"] = status
    return results


def load_profile(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"profile YAML must be a mapping: {path}")
    data["_profilePath"] = str(path)
    return data


def raw_from_exception(exc: Exception) -> str:
    return str(getattr(exc, "raw_output", "") or "")


def make_agent_log_dir() -> Path:
    log_dir = (
        Path("logs")
        / "agent"
        / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 3)


def finalize_timings(
    context: dict[str, Any],
    execution: dict[str, Any],
    total_started: float,
) -> dict[str, Any]:
    timings = dict(context.get("timings") or {})
    timings.update(execution.get("timings") or {})
    timings["totalSeconds"] = elapsed(total_started)
    return timings
