"""Safety evaluations and evidence traces assembled from Agent run summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tool_validator import is_inside_repo


def build_requirement_safety_evaluation(
    args: Any,
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
    clarification_only = (
        (planner_result.get("llmInput") or {}).get("mode")
        == "requirement-clarification"
    )
    return {
        "llmProviderPolicy": {
            "status": (
                "not-needed"
                if clarification_only
                else "passed"
                if planner_result.get("llmPlannerUsed")
                else "failed"
            ),
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
            "status": (
                "passed"
                if is_inside_repo(Path(context["workspace"]))
                and is_inside_repo(Path(context["targetProjectDir"]))
                else "failed"
            ),
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
            "status": "passed",
            "rule": "Log analysis uses validated deterministic evidence when Local LLM enrichment is skipped or unavailable; no external fallback is used.",
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
    return {
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
        "ragEvidence": build_rag_trace(
            summary.get("retrievalDetails") or {},
            summary.get("ragEvidence") or [],
        ),
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
            "validatedRecoveryToolCalls": (
                (recovery.get("plan") or {}).get("validatedRecoveryToolCalls") or []
            ),
            "rejectedRecoveryToolCalls": recovery.get("rejectedRecoveryToolCalls") or [],
        },
    }


def build_log_analysis_evidence_trace(summary: dict[str, Any]) -> dict[str, Any]:
    llm_analysis = summary.get("llmAnalysis") or {}
    return {
        "sourceLogEvidence": {
            "sourceLogDir": summary.get("sourceLogDir"),
            "sourceSummary": summary.get("sourceSummary"),
            "sourceAnalysis": summary.get("sourceAnalysis"),
            "warnings": summary.get("warnings") or [],
        },
        "ragEvidence": build_rag_trace(
            summary.get("retrievalDetails") or {},
            summary.get("ragEvidence") or [],
        ),
        "toolEvidence": build_execution_trace([summary.get("logAnalyzerResult") or {}]),
        "llmJudgmentEvidence": {
            "decision": llm_analysis.get("decision") or "",
            "classification": llm_analysis.get("classification") or "",
            "rootCause": llm_analysis.get("rootCause") or "",
            "evidence": llm_analysis.get("evidence") or [],
            "recommendedFixes": llm_analysis.get("recommendedFixes") or [],
        },
    }


def build_rag_trace(
    retrieval_details: dict[str, Any],
    llm_rag_evidence: list[Any],
) -> dict[str, Any]:
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


def tail_lines(text: str, count: int) -> str:
    return "\n".join(text.splitlines()[-count:])
