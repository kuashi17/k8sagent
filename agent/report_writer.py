"""Persistent Agent artifact and Tool log writer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


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

    write_json(log_dir / "summary.json", summary)
    write_optional_json(log_dir / "evidence-trace.json", summary.get("evidenceTrace"))
    write_optional_json(log_dir / "safety-evaluation.json", summary.get("safetyEvaluation"))
    write_optional_json(log_dir / "timings.json", summary.get("timings"))
    write_optional_json(log_dir / "planner-cache.json", summary.get("plannerCache"))
    write_json(log_dir / "initial-plan.json", planner_result.get("llmOutput") or {})
    write_json(log_dir / "validated-tool-calls.json", execution.get("validatedToolCalls") or [])
    write_json(log_dir / "rejected-tool-calls.json", execution.get("rejectedToolCalls") or [])
    write_json(log_dir / "deferred-tool-calls.json", execution.get("deferredToolCalls") or [])
    write_json(log_dir / "llm-input.json", planner_result.get("llmInput") or {})
    write_json(
        log_dir / "llm-output.json",
        llm_result_artifact(planner_result),
    )
    write_json(log_dir / "retrieved-docs.json", retrieved_docs)
    write_retrieval_artifacts(log_dir, summary.get("retrievalDetails") or {})
    write_json(log_dir / "tool-results.json", tool_results)
    write_tool_output_logs(log_dir, tool_results)
    (log_dir / "llm-raw-output.txt").write_text(planner_result.get("rawOutput") or "", encoding="utf-8")

    if final_result is not None:
        write_json(log_dir / "final-llm-input.json", final_result.get("llmInput") or {})
        write_json(log_dir / "final-llm-output.json", llm_result_artifact(final_result))

    recovery = summary.get("recovery") or {}
    failure_context = summary.get("failureContext") or {}
    if failure_context or recovery_result is not None:
        write_recovery_artifacts(
            log_dir,
            failure_context,
            recovery,
            recovery_result or {},
        )


def write_retrieval_artifacts(log_dir: Path, retrieval: dict[str, Any]) -> None:
    if not retrieval:
        return
    write_json(log_dir / "retrieval-query.json", retrieval.get("retrievalQuery") or {})
    write_json(log_dir / "vector-results.json", retrieval.get("vectorSearchResults") or [])
    write_json(log_dir / "keyword-results.json", retrieval.get("keywordSearchResults") or [])
    write_json(log_dir / "hybrid-results.json", retrieval.get("hybridResults") or [])
    write_json(
        log_dir / "reranker-input.json",
        (retrieval.get("rerankerOutput") or {}).get("allRankedResults") or [],
    )
    write_json(log_dir / "reranker-output.json", retrieval.get("rerankerOutput") or {})
    write_json(log_dir / "selected-context.json", retrieval.get("selectedContext") or [])


def write_recovery_artifacts(
    log_dir: Path,
    failure_context: dict[str, Any],
    recovery: dict[str, Any],
    recovery_result: dict[str, Any],
) -> None:
    write_json(log_dir / "failure-context.json", failure_context)
    write_json(
        log_dir / "retrieved-troubleshooting-docs.json",
        recovery.get("retrievedTroubleshootingDocs") or [],
    )
    write_optional_json(
        log_dir / "recovery-retrieval-details.json",
        recovery.get("retrievalDetails"),
    )
    write_json(log_dir / "raw-recovery-plan.json", recovery.get("rawPlan") or {})
    write_json(log_dir / "recovery-llm-input.json", recovery_result.get("llmInput") or {})
    (log_dir / "recovery-llm-raw-output.txt").write_text(
        recovery_result.get("rawOutput") or "",
        encoding="utf-8",
    )
    write_json(log_dir / "recovery-plan.json", recovery.get("plan") or {})
    write_json(log_dir / "validated-recovery-plan.json", recovery.get("plan") or {})
    write_json(
        log_dir / "rejected-recovery-tool-calls.json",
        recovery.get("rejectedRecoveryToolCalls") or [],
    )
    write_json(
        log_dir / "recovery-policy-evaluation.json",
        recovery.get("policyEvaluation") or {},
    )


def write_tool_output_logs(log_dir: Path, tool_results: list[dict[str, Any]]) -> None:
    for index, result in enumerate(tool_results, start=1):
        tool = safe_filename(str(result.get("tool") or f"tool-{index}"))
        prefix = f"{index:02d}-{tool}"
        (log_dir / f"{prefix}.stdout.log").write_text(str(result.get("stdout") or ""), encoding="utf-8")
        (log_dir / f"{prefix}.stderr.log").write_text(str(result.get("stderr") or ""), encoding="utf-8")
        for step_index, step in enumerate(result.get("steps") or [], start=1):
            target = safe_filename(str(step.get("target") or step_index))
            (log_dir / f"{prefix}-{step_index:02d}-{target}.stdout.log").write_text(
                str(step.get("stdout") or ""),
                encoding="utf-8",
            )
            (log_dir / f"{prefix}-{step_index:02d}-{target}.stderr.log").write_text(
                str(step.get("stderr") or ""),
                encoding="utf-8",
            )


def llm_result_artifact(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "planner": "llm",
        "localLLM": result.get("localLLM"),
        "llmPlannerUsed": result.get("llmPlannerUsed"),
        "error": result.get("error"),
        "output": result.get("llmOutput") or {},
        "rawOutput": result.get("rawOutput") or "",
    }


def write_optional_json(path: Path, value: Any) -> None:
    if value:
        write_json(path, value)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def safe_filename(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", value).strip("-")
