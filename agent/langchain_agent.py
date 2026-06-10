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

from agent.llm.client import LLMUnavailable, REQUIRED_ENV_MESSAGE  # noqa: E402
from agent.llm.planner import analyze_log_with_llm, plan_requirement_with_llm  # noqa: E402
from agent.rag.retriever import search as retrieve_knowledge  # noqa: E402
from agent.tools import langchain_wrappers as tools  # noqa: E402


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
        summary = build_requirement_summary(args, context, planner_result, [])
        write_agent_artifacts(log_dir, summary, planner_result, context["retrievedKnowledge"], [])
        report = render_requirement_report(summary)
        (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
        print(report)
        print(f"\nAgent logs: {log_dir}")
        return 2

    tool_results = execute_planned_tools(context, args.mode, args.execute, planner_result)
    summary = build_requirement_summary(args, context, planner_result, tool_results)
    write_agent_artifacts(log_dir, summary, planner_result, context["retrievedKnowledge"], tool_results)
    report = render_requirement_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 0 if not summary["errors"] else 1


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
    except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
        message = str(exc) or REQUIRED_ENV_MESSAGE
        print(f"LLM planner failed: {message}")
        return llm_result(False, llm_input, {}, "", message)


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
    retrieved = retrieve_knowledge(build_log_rag_query(source_summary, analysis_text), limit=8)[:5]
    planner_result = call_log_planner(source_summary, analysis_text, retrieved)

    errors = [] if analyzer_result["exitCode"] == 0 else ["log_analyzer failed"]
    if planner_result["error"]:
        errors.append("LLM planner failed")

    summary = {
        "mode": "log-analysis",
        "planner": "llm",
        "llmPlannerUsed": planner_result["llmPlannerUsed"],
        "llmError": planner_result["error"],
        "sourceLogDir": str(source_log_dir),
        "sourceSummary": str(source_summary_path),
        "sourceAnalysis": str(analysis_path),
        "createdAt": now_iso(),
        "logAnalyzerResult": analyzer_result,
        "retrievedKnowledge": retrieved,
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
    except (LLMUnavailable, Exception) as exc:  # noqa: BLE001
        message = str(exc) or REQUIRED_ENV_MESSAGE
        print(f"LLM planner failed: {message}")
        return llm_result(False, llm_input, {}, "", message)


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
    retrieved = retrieve_knowledge(requirement_text, limit=5)
    return {
        "requirement": str(requirement_path),
        "requirementSummary": summary,
        "missingInformation": missing_information(summary, requirement_text),
        "retrievedKnowledge": retrieved,
        "selectedProfile": {
            "path": profile_path or "",
            "name": profile.get("profileName", ""),
            "description": profile.get("description", ""),
            "managedResources": profile.get("managedResources") or [],
        },
        "workspace": workspace,
        "generatedFiles": {
            "operatorSpec": f"generated/{kind_slug}-operator-spec.yaml",
            "commandPlan": f"generated/{kind_slug}-command-plan.md",
        },
    }


def execute_planned_tools(
    context: dict[str, Any],
    mode: str,
    allow_execute: bool,
    planner_result: dict[str, Any],
) -> list[dict[str, Any]]:
    generated = context["generatedFiles"]
    mutating_execute = mode == "execute" and allow_execute
    supported_calls = {
        "spec_generator": lambda: tools.spec_generator(context["requirement"], generated["operatorSpec"]),
        "command_planner": lambda: tools.command_planner(generated["operatorSpec"], generated["commandPlan"], context["workspace"]),
        "scaffold_runner": lambda: tools.scaffold_runner(generated["operatorSpec"], context["workspace"], execute=mutating_execute),
        "artifact_patcher": lambda: tools.artifact_patcher(generated["operatorSpec"], "", context["selectedProfile"].get("path"), execute=mutating_execute),
        "e2e_runner": lambda: tools.e2e_runner(generated["operatorSpec"], context["selectedProfile"].get("path"), execute=mutating_execute),
    }
    calls = planned_tool_calls(planner_result, supported_calls)
    if not calls:
        print("\nLLM planner did not request any supported Tool calls.")
        return []

    results: list[dict[str, Any]] = []
    for name, call in calls:
        print(f"\nCalling tool: {name}")
        result = call()
        result["tool"] = name
        results.append(result)
        print(f"exitCode={result['exitCode']} status={result['status']}")
        if result["exitCode"] != 0:
            break
    return results


def planned_tool_calls(
    planner_result: dict[str, Any],
    supported_calls: dict[str, Any],
) -> list[tuple[str, Any]]:
    output = planner_result.get("llmOutput") or {}
    requested = output.get("toolCalls") if isinstance(output, dict) else None
    if not isinstance(requested, list):
        return []

    ordered: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for item in requested:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool") or "")
        if tool_name not in supported_calls or tool_name in seen:
            continue
        seen.add(tool_name)
        ordered.append((tool_name, supported_calls[tool_name]))
    return ordered


def build_requirement_summary(
    args: argparse.Namespace,
    context: dict[str, Any],
    planner_result: dict[str, Any],
    tool_results: list[dict[str, Any]],
) -> dict[str, Any]:
    errors = collect_errors(tool_results)
    if planner_result["error"]:
        errors.append(planner_result["error"])
    if planner_result["llmPlannerUsed"] and not planned_tool_calls(
        planner_result,
        {"spec_generator": None, "command_planner": None, "scaffold_runner": None, "artifact_patcher": None, "e2e_runner": None},
    ):
        errors.append("LLM output did not include supported toolCalls.")
    return {
        "mode": "requirement-planning",
        "requirement": context["requirement"],
        "profile": args.profile or "",
        "planner": "llm",
        "llmPlannerUsed": planner_result["llmPlannerUsed"],
        "llmError": planner_result["error"],
        "agentMode": args.mode,
        "executeAllowed": bool(args.execute),
        "createdAt": now_iso(),
        "requirementSummary": context["requirementSummary"],
        "missingInformation": context["missingInformation"],
        "retrievedKnowledge": context["retrievedKnowledge"],
        "selectedProfile": context["selectedProfile"],
        "llmPlan": planner_result.get("llmOutput") or {},
        "llmReasoning": extract_list(planner_result.get("llmOutput") or {}, "reasoning"),
        "ragEvidence": extract_list(planner_result.get("llmOutput") or {}, "ragEvidence"),
        "toolCallPlan": extract_tool_call_plan(planner_result.get("llmOutput") or {}),
        "generatedFiles": context["generatedFiles"],
        "toolResults": tool_results,
        "warnings": collect_warnings(tool_results, context),
        "errors": errors,
        "nextRecommendedActions": next_actions(context, tool_results, planner_result),
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
) -> list[str]:
    llm_actions = (planner_result.get("llmOutput") or {}).get("nextActions") or []
    actions = [str(item) for item in llm_actions if item]
    if any(result["exitCode"] != 0 for result in tool_results):
        actions.insert(0, "실패한 Tool의 stderr와 생성된 summary를 먼저 확인합니다.")
    if planner_result["error"]:
        actions.append(REQUIRED_ENV_MESSAGE)
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
    lines.extend([f"- {item}" for item in llm_analysis.get("recommendedFixes") or []] or ["- Check LLM error and required environment variables."])
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


def write_agent_artifacts(
    log_dir: Path,
    summary: dict[str, Any],
    planner_result: dict[str, Any],
    retrieved_docs: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> None:
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (log_dir / "llm-input.json").write_text(json.dumps(planner_result.get("llmInput") or {}, indent=2, ensure_ascii=False), encoding="utf-8")
    (log_dir / "llm-output.json").write_text(
        json.dumps(
            {
                "planner": "llm",
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
    (log_dir / "tool-results.json").write_text(json.dumps(tool_results, indent=2, ensure_ascii=False), encoding="utf-8")


def make_agent_log_dir() -> Path:
    log_dir = Path("logs") / "agent" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
