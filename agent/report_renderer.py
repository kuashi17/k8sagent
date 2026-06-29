"""Markdown renderers for Agent requirement and log-analysis reports."""

from __future__ import annotations

import json
from typing import Any


def render_requirement_report(summary: dict[str, Any]) -> str:
    requirement = summary.get("requirementSummary") or {}
    lines = [
        "# Agent Run Report",
        "",
        "## Planner",
        "",
        "- Planner: `llm`",
        f"- Local LLM endpoint: `{(summary.get('localLLM') or {}).get('baseUrl') or 'unknown'}`",
        f"- Local LLM model: `{(summary.get('localLLM') or {}).get('model') or 'unknown'}`",
        f"- LLM planner used: `{summary.get('llmPlannerUsed')}`",
        f"- LLM error: `{summary.get('llmError') or 'none'}`",
        f"- Planner cache hit: `{(summary.get('plannerCache') or {}).get('hit', False)}`",
        f"- Run level: `{summary.get('runLevel') or 'standard'}`",
        "",
        "## Timings",
        "",
        *format_timings(summary.get("timings") or {}),
        "",
        "## Requirement Summary",
        "",
        f"- Kind: `{requirement.get('kind') or 'unknown'}`",
        f"- API: `{requirement.get('group') or 'unknown'}/{requirement.get('version') or 'unknown'}`",
        f"- Managed resources: `{', '.join(requirement.get('managedResources') or []) or 'unknown'}`",
        f"- Observed resources: `{', '.join(requirement.get('observedResources') or []) or 'none'}`",
        f"- Spec fields: `{', '.join(requirement.get('specFields') or []) or 'none'}`",
        f"- Status fields: `{', '.join(requirement.get('statusFields') or []) or 'none'}`",
        "",
        "## Missing Information",
        "",
        *bullet_lines(summary.get("missingInformation") or [], "No critical missing information found."),
        "",
        "## Retrieved Knowledge",
        "",
        *format_retrieved_docs(summary.get("retrievedKnowledge") or []),
    ]
    if summary.get("llmPlan"):
        lines.extend(["", "## LLM Planner Output", "", json_block(summary["llmPlan"])])
    lines.extend(["", "## RAG Evidence", "", *format_rag_evidence(summary.get("ragEvidence") or [])])
    lines.extend(["", "## Evidence Trace", "", *format_evidence_trace(summary.get("evidenceTrace") or {})])
    lines.extend(["", "## Tool Call Plan", "", *format_tool_call_plan(summary.get("toolCallPlan") or [])])
    lines.extend(
        [
            "",
            "## Tool Validation",
            "",
            *format_validated_tool_calls(summary.get("validatedToolCalls") or []),
        ]
    )
    append_optional_calls(lines, "Rejected Tool Calls", summary.get("rejectedToolCalls") or [])
    append_optional_calls(lines, "Deferred Tool Calls", summary.get("deferredToolCalls") or [])
    lines.extend(["", "## Safety Evaluation", "", *format_safety_evaluation(summary.get("safetyEvaluation") or {})])
    append_profile(lines, summary)
    append_tool_results(lines, summary.get("toolResults") or [])
    append_kind_result(lines, summary.get("toolResults") or [])
    append_recovery(lines, summary.get("recovery") or {})
    append_final_evaluation(lines, summary.get("finalLLM") or {})
    generated = summary.get("generatedFiles") or {}
    lines.extend(
        [
            "",
            "## Generated Files",
            "",
            f"- Operator spec: `{generated.get('operatorSpec') or 'none'}`",
            f"- Command plan: `{generated.get('commandPlan') or 'none'}`",
            "",
            "## Warnings / Errors",
            "",
            *bullet_lines(summary.get("warnings") or [], "Warnings: none", prefix="Warning: "),
            *bullet_lines(summary.get("errors") or [], "Errors: none", prefix="Error: "),
            "",
            "## Next Recommended Actions",
            "",
            *bullet_lines(summary.get("nextRecommendedActions") or [], "No next action was generated."),
        ]
    )
    return "\n".join(lines) + "\n"


def render_log_analysis_report(summary: dict[str, Any]) -> str:
    analysis = summary.get("llmAnalysis") or {}
    analyzer = summary.get("logAnalyzerResult") or {}
    lines = [
        "# Agent Log Analysis Report",
        "",
        "## Planner",
        "",
        f"- Local LLM model: `{(summary.get('localLLM') or {}).get('model') or 'unknown'}`",
        f"- LLM planner used: `{summary.get('llmPlannerUsed')}`",
        f"- LLM error: `{summary.get('llmError') or 'none'}`",
        "",
        "## Overall Result",
        "",
        f"- Source log dir: `{summary.get('sourceLogDir') or 'unknown'}`",
        f"- Decision: `{analysis.get('decision') or 'unknown'}`",
        f"- Classification: `{analysis.get('classification') or 'unknown'}`",
        f"- Root cause: {analysis.get('rootCause') or 'unknown'}",
        "",
        "## Evidence",
        "",
        *bullet_lines(analysis.get("evidence") or [], "No LLM evidence was generated."),
        "",
        "## RAG Evidence",
        "",
        *format_rag_evidence(summary.get("ragEvidence") or []),
        "",
        "## Evidence Trace",
        "",
        *format_evidence_trace(summary.get("evidenceTrace") or {}),
        "",
        "## Safety Evaluation",
        "",
        *format_safety_evaluation(summary.get("safetyEvaluation") or {}),
    ]
    if analysis.get("explanationForBeginner"):
        lines.extend(["", "## Beginner Explanation", "", str(analysis["explanationForBeginner"])])
    if analysis:
        lines.extend(["", "## LLM Analysis Output", "", json_block(analysis)])
    lines.extend(
        [
            "",
            "## Retrieved Troubleshooting Knowledge",
            "",
            *format_retrieved_docs(summary.get("retrievedKnowledge") or []),
            "",
            "## Tool Result",
            "",
            f"- log_analyzer: `{analyzer.get('status') or 'unknown'}` exitCode=`{analyzer.get('exitCode')}`",
            f"- command: `{' '.join(analyzer.get('command') or [])}`",
            "",
            "## Next Actions",
            "",
            *bullet_lines(
                analysis.get("recommendedFixes") or [],
                "Check Ollama local LLM server and model availability.",
            ),
        ]
    )
    if analysis.get("rerunCommand"):
        lines.append(f"- Recommended re-run: `{analysis['rerunCommand']}`")
    return "\n".join(lines) + "\n"


def append_profile(lines: list[str], summary: dict[str, Any]) -> None:
    profile = summary.get("selectedProfile") or {}
    lines.extend(
        [
            "",
            "## Profile Hint",
            "",
            f"- Path: `{profile.get('path') or 'none'}`",
            f"- Name: `{profile.get('name') or 'none'}`",
            f"- Selection mode: `{profile.get('selectionMode') or 'unknown'}`",
            f"- Role: `hint-only`",
        ]
    )


def append_tool_results(lines: list[str], results: list[dict[str, Any]]) -> None:
    lines.extend(["", "## Tool Execution Results", ""])
    if not results:
        lines.append("- No tools were executed.")
        return
    for result in results:
        lines.append(f"- `{result.get('tool')}`: {result.get('status')} exitCode={result.get('exitCode')}")
        lines.append(f"  - command: `{' '.join(result.get('command') or [])}`")


def append_kind_result(lines: list[str], results: list[dict[str, Any]]) -> None:
    deployments = [item.get("deploymentSummary") or {} for item in results if item.get("tool") == "kind_deployment"]
    if not deployments:
        return
    deployment = deployments[-1]
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
        ]
    )


def append_recovery(lines: list[str], recovery: dict[str, Any]) -> None:
    if not recovery.get("waitingForUserApproval"):
        return
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
            "### Validated Recovery Tool Calls",
            "",
        ]
    )
    calls = plan.get("validatedRecoveryToolCalls") or []
    if calls:
        for item in calls:
            lines.append(
                f"- `{item.get('tool')}` mode=`{item.get('mode')}` requiresApproval=`{item.get('requiresApproval')}`"
            )
            lines.append(f"  - reason: {item.get('reason') or 'not specified'}")
    else:
        lines.append("- No recovery Tool calls were generated.")
    lines.extend(["", "No recovery Tool was executed. Waiting for user approval."])


def append_final_evaluation(lines: list[str], final: dict[str, Any]) -> None:
    output = final.get("output") or {}
    lines.extend(["", "## Final LLM Evaluation", ""])
    if output:
        if final.get("fallbackUsed"):
            lines.append(
                "- fallback: deterministic Tool-result summary "
                f"(`{final.get('fallbackError') or 'LLM evaluation failed'}`)"
            )
        lines.extend(
            [
                f"- executionDecision: `{output.get('executionDecision') or 'unknown'}`",
                f"- completedSteps: `{', '.join(str(item) for item in output.get('completedSteps') or []) or 'none'}`",
                f"- failedSteps: `{', '.join(str(item) for item in output.get('failedSteps') or []) or 'none'}`",
                "",
                json_block(output),
            ]
        )
    else:
        lines.append(f"- {final.get('error') or 'Final LLM evaluation was not generated.'}")


def append_optional_calls(lines: list[str], title: str, items: list[dict[str, Any]]) -> None:
    if items:
        lines.extend(["", f"## {title}", "", *format_rejected_tool_calls(items)])


def format_retrieved_docs(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- No matching knowledge document found."]
    return [
        f"- `{item.get('path') or item.get('sourcePath') or 'unknown'}`: {item.get('title') or 'untitled'}"
        for item in items
    ]


def format_timings(timings: dict[str, Any]) -> list[str]:
    if not timings:
        return ["- No timing information was recorded."]
    labels = {
        "ragRetrievalSeconds": "RAG retrieval",
        "llmPlanningSeconds": "Initial LLM planning",
        "toolValidationSeconds": "Tool validation",
        "toolExecutionSeconds": "Tool execution",
        "finalLlmEvaluationSeconds": "Final LLM evaluation",
        "recoveryPlanningSeconds": "Recovery planning",
        "totalSeconds": "Total",
    }
    lines = ["| Stage | Seconds |", "|---|---:|"]
    for key, value in timings.items():
        label = labels.get(key, key)
        try:
            lines.append(f"| {label} | {float(value):.3f} |")
        except (TypeError, ValueError):
            lines.append(f"| {label} | {value} |")
    return lines


def format_rag_evidence(items: list[Any]) -> list[str]:
    if not items:
        return ["- No explicit RAG evidence mapping was generated."]
    lines = []
    for item in items:
        if isinstance(item, dict):
            lines.append(f"- `{item.get('documentPath') or item.get('path') or 'unknown'}`: {item.get('usedFor') or item.get('reason') or 'not specified'}")
        else:
            lines.append(f"- {item}")
    return lines


def format_tool_call_plan(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- No supported Tool call plan was generated."]
    lines = []
    for item in items:
        lines.append(f"- `{item.get('tool') or 'unknown'}` mode=`{item.get('mode') or 'unspecified'}`")
        lines.append(f"  - reason: {item.get('reason') or 'No reason provided.'}")
    return lines


def format_validated_tool_calls(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- No Tool calls were validated."]
    return [
        f"- `{item.get('tool')}` requested=`{item.get('requestedMode')}` effective=`{item.get('effectiveMode')}`"
        for item in items
    ]


def format_rejected_tool_calls(items: list[dict[str, Any]]) -> list[str]:
    return [f"- `{item.get('tool') or 'unknown'}`: {item.get('reason') or 'not specified'}" for item in items]


def format_safety_evaluation(data: dict[str, Any]) -> list[str]:
    if not data:
        return ["- No safety evaluation was recorded."]
    lines = []
    for name, item in data.items():
        if isinstance(item, dict):
            lines.append(f"- `{name}`: `{item.get('status') or 'unknown'}`")
            if item.get("rule"):
                lines.append(f"  - rule: {item['rule']}")
    return lines or ["- No safety evaluation entries were recorded."]


def format_evidence_trace(data: dict[str, Any]) -> list[str]:
    if not data:
        return ["- No evidence trace was recorded."]
    validation = data.get("toolValidationEvidence") or {}
    execution = data.get("executionEvidence") or []
    lines = [
        "- Tool validation: "
        f"validated={len(validation.get('validatedToolCalls') or [])}, "
        f"rejected={len(validation.get('rejectedToolCalls') or [])}, "
        f"deferred={len(validation.get('deferredToolCalls') or [])}"
    ]
    for item in execution:
        if isinstance(item, dict):
            lines.append(f"- `{item.get('tool')}` status=`{item.get('status')}` exitCode=`{item.get('exitCode')}`")
    return lines


def bullet_lines(items: list[Any], empty: str, prefix: str = "") -> list[str]:
    return [f"- {prefix}{item}" for item in items] if items else [f"- {empty}"]


def json_block(value: Any) -> str:
    return "```json\n" + json.dumps(value, indent=2, ensure_ascii=False) + "\n```"
