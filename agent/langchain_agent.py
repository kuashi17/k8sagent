#!/usr/bin/env python3
"""LangChain-style Agent orchestrator for the Kubebuilder automation MVP.

The default planner is `mock`, a deterministic planner that demonstrates the
Agent loop without requiring an external LLM API. The code is structured so a
future planner can replace the mock planner with ChatOpenAI or a local LLM.
"""

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

from agent.rag.retriever import search as retrieve_knowledge  # noqa: E402
from agent.tools import langchain_wrappers as tools  # noqa: E402
from agent.llm.client import LLMUnavailable, config_from_env  # noqa: E402
from agent.llm.planner import analyze_log_with_llm, plan_requirement_with_llm  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LangChain-style Kubebuilder Agent orchestrator.")
    parser.add_argument("--requirement", help="Natural language requirement file.")
    parser.add_argument("--log-dir", help="Existing logs/scaffold, logs/patch, or logs/e2e directory to analyze.")
    parser.add_argument("--analyze-log", help="Alias of --log-dir. Analyze an existing execution log with RAG context.")
    parser.add_argument("--profile", help="Profile YAML path.")
    parser.add_argument("--planner", default="mock", choices=["mock", "llm", "local"], help="Planner type. mock is the safe default.")
    parser.add_argument("--mode", default="dry-run", choices=["dry-run", "execute"], help="Agent mode. Defaults to dry-run.")
    parser.add_argument("--workspace", default="workspace/generated-operators", help="Scaffold workspace parent.")
    parser.add_argument("--execute", action="store_true", help="Allow real execution for mutating tools. Not used by the mock dry-run flow.")
    args = parser.parse_args()

    if args.analyze_log and not args.log_dir:
        args.log_dir = args.analyze_log
    if args.log_dir:
        return run_log_analysis_agent(args)
    if not args.requirement:
        raise SystemExit("--requirement is required unless --log-dir or --analyze-log is provided.")

    requirement_path = Path(args.requirement)
    requirement_text = requirement_path.read_text(encoding="utf-8")
    profile = load_profile(Path(args.profile)) if args.profile else {}
    plan = build_mock_plan(requirement_path, requirement_text, args.profile, profile, args.workspace)
    planner_result = build_requirement_planner_result(args, requirement_text, plan, profile)

    log_dir = Path("logs") / "agent" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)

    print_agent_header(plan)
    tool_results = execute_plan(plan, mode=args.mode, allow_execute=args.execute, planner_result=planner_result)

    summary = {
        "requirement": str(requirement_path),
        "profile": args.profile or "",
        "planner": args.planner,
        "effectivePlanner": planner_result["effectivePlanner"],
        "plannerFallback": planner_result["fallback"],
        "llmPlan": planner_result.get("llmOutput"),
        "llmError": planner_result.get("error", ""),
        "mode": args.mode,
        "executeAllowed": bool(args.execute),
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "requirementSummary": plan["requirementSummary"],
        "missingInformation": plan["missingInformation"],
        "retrievedKnowledge": plan["retrievedKnowledge"],
        "selectedProfile": plan["selectedProfile"],
        "plannedSteps": plan["plannedSteps"],
        "generatedFiles": plan["generatedFiles"],
        "toolResults": tool_results,
        "warnings": collect_warnings(tool_results, plan, planner_result),
        "errors": collect_errors(tool_results),
        "nextRecommendedActions": next_actions(plan, tool_results),
    }
    write_agent_artifacts(log_dir, summary, planner_result, plan["retrievedKnowledge"], tool_results)
    report = render_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")

    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 0 if not summary["errors"] else 1


def build_requirement_planner_result(
    args: argparse.Namespace,
    requirement_text: str,
    mock_plan: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    if args.planner == "mock":
        return {
            "requestedPlanner": "mock",
            "effectivePlanner": "mock",
            "fallback": False,
            "llmInput": {},
            "llmOutput": {},
            "rawOutput": "",
            "error": "",
        }
    profile_summary = mock_plan["selectedProfile"]
    try:
        config = config_from_env(provider="local") if args.planner == "local" else None
        output, llm_input, raw = plan_requirement_with_llm(
            requirement_text,
            mock_plan["retrievedKnowledge"],
            profile_summary,
            args.mode,
            config=config,
        )
        return {
            "requestedPlanner": args.planner,
            "effectivePlanner": args.planner,
            "fallback": False,
            "llmInput": llm_input,
            "llmOutput": output,
            "rawOutput": raw,
            "error": "",
        }
    except (LLMUnavailable, NotImplementedError, Exception) as exc:  # noqa: BLE001
        message = f"{exc} Fallback to mock planner."
        print(f"LLM planner unavailable: {message}")
        return {
            "requestedPlanner": args.planner,
            "effectivePlanner": "mock",
            "fallback": True,
            "llmInput": {
                "mode": "requirement-planning",
                "requirementText": requirement_text,
                "retrievedDocs": mock_plan["retrievedKnowledge"],
                "profileSummary": profile_summary,
                "safetyMode": args.mode,
            },
            "llmOutput": {},
            "rawOutput": "",
            "error": message,
        }


def run_log_analysis_agent(args: argparse.Namespace) -> int:
    log_dir_input = Path(args.log_dir)
    source_summary_path = log_dir_input / "summary.json"
    if not source_summary_path.is_file():
        raise SystemExit(f"summary.json not found under log directory: {log_dir_input}")

    source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
    log_dir = Path("logs") / "agent" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)

    print("LangChain-style Agent Log Analysis")
    print(f"Source log dir: {log_dir_input}")
    print("\nCalling tool: log_analyzer")
    analyzer_result = tools.log_analyzer(str(log_dir_input))
    analyzer_result["tool"] = "log_analyzer"
    print(f"exitCode={analyzer_result['exitCode']} status={analyzer_result['status']}")

    analysis_path = log_dir_input / "analysis.md"
    analysis_text = analysis_path.read_text(encoding="utf-8") if analysis_path.is_file() else ""
    query = build_log_rag_query(source_summary, analysis_text)
    retrieved = filter_log_knowledge(source_summary, retrieve_knowledge(query, limit=8))[:5]
    reasoning = reason_about_log(source_summary, analysis_text, retrieved, analyzer_result)
    planner_result = build_log_planner_result(args, source_summary, analysis_text, retrieved, reasoning)

    summary = {
        "mode": "log-analysis",
        "sourceLogDir": str(log_dir_input),
        "sourceSummary": str(source_summary_path),
        "sourceAnalysis": str(analysis_path),
        "profile": args.profile or source_summary.get("profileConfig", {}).get("profilePath", ""),
        "planner": args.planner,
        "effectivePlanner": planner_result["effectivePlanner"],
        "plannerFallback": planner_result["fallback"],
        "llmAnalysis": planner_result.get("llmOutput"),
        "llmError": planner_result.get("error", ""),
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "logAnalyzerResult": analyzer_result,
        "retrievedKnowledge": retrieved,
        "reasoning": reasoning,
        "warnings": (source_summary.get("warnings") or []) + ([f"Planner fallback: {planner_result['error']}"] if planner_result["fallback"] else []),
        "errors": [] if analyzer_result["exitCode"] == 0 else ["log_analyzer failed"],
    }
    write_agent_artifacts(log_dir, summary, planner_result, retrieved, [analyzer_result])
    report = render_log_analysis_report(summary)
    (log_dir / "agent-report.md").write_text(report, encoding="utf-8")
    print(report)
    print(f"\nAgent logs: {log_dir}")
    return 0 if not summary["errors"] else 1


def build_log_planner_result(
    args: argparse.Namespace,
    source_summary: dict[str, Any],
    analysis_text: str,
    retrieved: list[dict[str, Any]],
    mock_reasoning: dict[str, Any],
) -> dict[str, Any]:
    if args.planner == "mock":
        return {
            "requestedPlanner": "mock",
            "effectivePlanner": "mock",
            "fallback": False,
            "llmInput": {},
            "llmOutput": {},
            "rawOutput": "",
            "error": "",
        }
    try:
        config = config_from_env(provider="local") if args.planner == "local" else None
        output, llm_input, raw = analyze_log_with_llm(source_summary, analysis_text, retrieved, config=config)
        return {
            "requestedPlanner": args.planner,
            "effectivePlanner": args.planner,
            "fallback": False,
            "llmInput": llm_input,
            "llmOutput": output,
            "rawOutput": raw,
            "error": "",
        }
    except (LLMUnavailable, NotImplementedError, Exception) as exc:  # noqa: BLE001
        message = f"{exc} Fallback to mock planner."
        print(f"LLM planner unavailable: {message}")
        return {
            "requestedPlanner": args.planner,
            "effectivePlanner": "mock",
            "fallback": True,
            "llmInput": {
                "mode": "log-analysis",
                "summary": source_summary,
                "analysisMd": analysis_text,
                "retrievedDocs": retrieved,
                "mockReasoning": mock_reasoning,
            },
            "llmOutput": {},
            "rawOutput": "",
            "error": message,
        }


def load_profile(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"profile YAML must be a mapping: {path}")
    data["_profilePath"] = str(path)
    return data


def build_mock_plan(
    requirement_path: Path,
    requirement_text: str,
    profile_path: str | None,
    profile: dict[str, Any],
    workspace: str,
) -> dict[str, Any]:
    summary = summarize_requirement(requirement_text)
    kind = summary.get("kind") or "operator"
    kind_slug = kind.lower()
    spec_output = f"generated/{kind_slug}-operator-spec.yaml"
    command_plan_output = f"generated/{kind_slug}-command-plan.md"
    retrieved = retrieve_knowledge(requirement_text, limit=5)
    selected_profile = {
        "path": profile_path or "",
        "name": profile.get("profileName", ""),
        "description": profile.get("description", ""),
        "managedResources": profile.get("managedResources") or [],
    }

    return {
        "requirement": str(requirement_path),
        "requirementSummary": summary,
        "missingInformation": missing_information(summary, requirement_text),
        "retrievedKnowledge": retrieved,
        "selectedProfile": selected_profile,
        "workspace": workspace,
        "generatedFiles": {
            "operatorSpec": spec_output,
            "commandPlan": command_plan_output,
        },
        "plannedSteps": [
            {
                "name": "spec_generator",
                "purpose": "자연어 요구사항을 구조화된 operator-spec.yaml로 변환합니다.",
            },
            {
                "name": "command_planner",
                "purpose": "operator-spec.yaml을 사람이 검토할 수 있는 Kubebuilder 실행 계획으로 변환합니다.",
            },
            {
                "name": "scaffold_runner_dry_run",
                "purpose": "실제 파일 생성 없이 Kubebuilder scaffold에서 실행될 명령을 확인합니다.",
            },
        ],
    }


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


def execute_plan(
    plan: dict[str, Any],
    mode: str,
    allow_execute: bool,
    planner_result: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    generated = plan["generatedFiles"]
    requirement = plan["requirement"]
    workspace = plan["workspace"]
    spec_path = generated["operatorSpec"]
    command_plan = generated["commandPlan"]

    mutating_execute = mode == "execute" and allow_execute
    supported_calls = {
        "spec_generator": lambda: tools.spec_generator(requirement, spec_path),
        "command_planner": lambda: tools.command_planner(spec_path, command_plan, workspace),
        "scaffold_runner": lambda: tools.scaffold_runner(spec_path, workspace, execute=mutating_execute),
        "scaffold_runner_dry_run": lambda: tools.scaffold_runner(spec_path, workspace, execute=False),
    }
    calls = planned_tool_calls(planner_result, supported_calls)

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
    planner_result: dict[str, Any] | None,
    supported_calls: dict[str, Any],
) -> list[tuple[str, Any]]:
    default_order = ["spec_generator", "command_planner", "scaffold_runner"]
    llm_output = (planner_result or {}).get("llmOutput") or {}
    requested = llm_output.get("toolCalls") if isinstance(llm_output, dict) else None
    if not requested:
        return [(name, supported_calls[name]) for name in default_order]

    ordered: list[tuple[str, Any]] = []
    seen: set[str] = set()
    for item in requested:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool") or "")
        if tool_name == "scaffold_runner" and str(item.get("mode") or "").lower() == "dry-run":
            tool_name = "scaffold_runner_dry_run"
        if tool_name not in supported_calls or tool_name in seen:
            continue
        seen.add(tool_name)
        ordered.append((tool_name, supported_calls[tool_name]))

    for name in default_order:
        if name not in seen and name in supported_calls:
            ordered.append((name, supported_calls[name]))
    return ordered


def print_agent_header(plan: dict[str, Any]) -> None:
    print("LangChain-style Agent Orchestrator")
    print(f"Requirement: {plan['requirement']}")
    print(f"Selected profile: {plan['selectedProfile'].get('path') or '<none>'}")
    print("Default safety mode: dry-run")


def write_agent_artifacts(
    log_dir: Path,
    summary: dict[str, Any],
    planner_result: dict[str, Any],
    retrieved_docs: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> None:
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (log_dir / "llm-input.json").write_text(
        json.dumps(planner_result.get("llmInput") or {}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (log_dir / "llm-output.json").write_text(
        json.dumps(
            {
                "requestedPlanner": planner_result.get("requestedPlanner"),
                "effectivePlanner": planner_result.get("effectivePlanner"),
                "fallback": planner_result.get("fallback"),
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


def collect_warnings(tool_results: list[dict[str, Any]], plan: dict[str, Any], planner_result: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if planner_result.get("fallback"):
        warnings.append(f"Planner fallback: {planner_result.get('error')}")
    if plan["missingInformation"]:
        warnings.append("Requirement has missing or weakly inferred information: " + ", ".join(plan["missingInformation"]))
    for result in tool_results:
        if "Warnings:" in result.get("stdout", ""):
            warnings.append(f"{result['tool']} reported warnings.")
    return warnings


def collect_errors(tool_results: list[dict[str, Any]]) -> list[str]:
    return [f"{result['tool']} failed with exit code {result['exitCode']}" for result in tool_results if result["exitCode"] != 0]


def next_actions(plan: dict[str, Any], tool_results: list[dict[str, Any]]) -> list[str]:
    spec_path = plan["generatedFiles"]["operatorSpec"]
    command_plan = plan["generatedFiles"]["commandPlan"]
    workspace = plan["workspace"]
    actions = [
        f"검토: {command_plan}",
        f"scaffold preflight: python3 agent/tools/scaffold_runner.py --input {spec_path} --workspace {workspace} --preflight",
        f"scaffold 실행 승인 후: python3 agent/tools/scaffold_runner.py --input {spec_path} --workspace {workspace} --execute",
    ]
    if any(result["exitCode"] != 0 for result in tool_results):
        actions.insert(0, "실패한 Tool의 stderr와 생성된 summary를 먼저 확인합니다.")
    return actions


def render_report(summary: dict[str, Any]) -> str:
    req = summary["requirementSummary"]
    lines = [
        "# Agent Run Report",
        "",
        "## Planner",
        "",
        f"- Requested planner: `{summary.get('planner')}`",
        f"- Effective planner: `{summary.get('effectivePlanner')}`",
        f"- Fallback used: `{summary.get('plannerFallback')}`",
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
    if summary["retrievedKnowledge"]:
        for item in summary["retrievedKnowledge"]:
            lines.append(f"- `{item['path']}`: {item['title']} ({', '.join(item['matchedKeywords'])})")
    else:
        lines.append("- No matching knowledge document found.")

    if summary.get("llmPlan"):
        lines.extend(
            [
                "",
                "## LLM Planner Output",
                "",
                "```json",
                json.dumps(summary["llmPlan"], indent=2, ensure_ascii=False),
                "```",
            ]
        )

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
            "## Planned Steps",
            "",
        ]
    )
    for step in summary["plannedSteps"]:
        lines.append(f"- `{step['name']}`: {step['purpose']}")

    lines.extend(["", "## Tool Execution Results", ""])
    for result in summary["toolResults"]:
        command = " ".join(result["command"])
        lines.append(f"- `{result['tool']}`: {result['status']} exitCode={result['exitCode']}")
        lines.append(f"  - command: `{command}`")

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


def build_log_rag_query(summary: dict[str, Any], analysis_text: str) -> str:
    parts = [
        "Kubebuilder e2e troubleshooting log analysis",
        str(summary.get("failedStep") or "succeeded"),
        " ".join(str(item) for item in summary.get("warnings") or []),
        json.dumps(summary.get("jobSpecValidation") or {}, ensure_ascii=False),
        json.dumps(summary.get("profileConfig") or {}, ensure_ascii=False),
        analysis_text[:2000],
    ]
    return "\n".join(parts)


def filter_log_knowledge(summary: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_name = str((summary.get("profileConfig") or {}).get("profileName") or "").lower()
    if not profile_name:
        return results

    filtered = []
    for item in results:
        path = item.get("path", "")
        if path.startswith("knowledge-base/examples/") and profile_name not in path.lower():
            continue
        filtered.append(item)
    return filtered or results


def reason_about_log(
    summary: dict[str, Any],
    analysis_text: str,
    retrieved: list[dict[str, Any]],
    analyzer_result: dict[str, Any],
) -> dict[str, Any]:
    failed_step = summary.get("failedStep")
    warnings = summary.get("warnings") or []
    job_validation = summary.get("jobSpecValidation") or {}
    profile = summary.get("profileConfig") or {}
    step_counts = count_source_steps(summary.get("steps") or [])
    classification = infer_log_classification(summary, analysis_text)

    if failed_step:
        decision = "failed"
        reason = f"`{failed_step}` 단계에서 실패가 기록되어 e2e 검증 실패로 판단합니다."
    elif job_validation.get("passed") is True:
        decision = "succeeded-with-warning" if warnings else "succeeded"
        reason = "모든 실행 단계가 실패 없이 끝났고 Job spec validation이 통과했으므로 성공으로 판단합니다."
    else:
        decision = "needs-review"
        reason = "명시적 failedStep은 없지만 Job spec validation 통과 여부가 불명확하므로 추가 확인이 필요합니다."

    if any("gpu" in str(item).lower() for item in warnings):
        reason += " Pod Pending은 GPU 리소스 부족 warning으로 기록되었고, kind 환경에서는 Job spec 검증이 성공했다면 실패로 보지 않습니다."

    evidence = [
        f"failedStep={failed_step}",
        f"warnings={len(warnings)}",
        f"jobSpecValidation.passed={job_validation.get('passed')}",
        f"profile={profile.get('profileName') or 'unknown'}",
        f"logAnalyzer.exitCode={analyzer_result.get('exitCode')}",
    ]
    gpu_pending_explanation = gpu_pending_explanation_for(summary, warnings, job_validation)

    return {
        "decision": decision,
        "classification": classification,
        "reason": reason,
        "evidence": evidence,
        "gpuPendingExplanation": gpu_pending_explanation,
        "stepCounts": step_counts,
        "jobSpecValidation": summarize_job_validation(job_validation),
        "nextActions": log_next_actions(summary, decision),
        "knowledgeUsed": [item["path"] for item in retrieved],
    }


def count_source_steps(steps: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for step in steps:
        status = str(step.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    counts["total"] = len(steps)
    return counts


def infer_log_classification(summary: dict[str, Any], analysis_text: str) -> str:
    text = "\n".join(
        [
            analysis_text.lower(),
            " ".join(str(item).lower() for item in summary.get("warnings") or []),
            json.dumps(summary.get("jobSpecValidation") or {}, ensure_ascii=False).lower(),
        ]
    )
    if summary.get("failedStep"):
        if "forbidden" in text:
            return "rbac-forbidden"
        if "pvc" in text or "persistentvolumeclaim" in text:
            return "pvc-not-found"
        if "imagepull" in text or "failed to pull image" in text:
            return "image-pull"
        return "failed-unknown"
    if "gpu" in text and "pending" in text:
        return "succeeded-with-gpu-pending-warning"
    return "succeeded"


def gpu_pending_explanation_for(summary: dict[str, Any], warnings: list[Any], job_validation: dict[str, Any]) -> dict[str, Any]:
    has_gpu_warning = any("gpu" in str(item).lower() for item in warnings)
    if not has_gpu_warning:
        return {
            "present": False,
            "message": "GPU Pending warning was not detected.",
        }

    expected = summary.get("expected") or {}
    profile = summary.get("profileConfig") or {}
    gpu_resource = profile.get("gpuResourceName") or "nvidia.com/gpu"
    return {
        "present": True,
        "message": (
            "Controller가 Job을 생성하지 못한 오류가 아닙니다. "
            "Job spec validation은 성공했고, kind 클러스터에 "
            f"`{gpu_resource}` 리소스가 없어 Pod가 Pending 상태로 남은 케이스입니다."
        ),
        "gpuResourceName": gpu_resource,
        "requestedGpuCount": expected.get("gpuCount"),
        "jobSpecValidationPassed": job_validation.get("passed"),
        "operatorFault": False,
        "recommendedFix": (
            "GPU 노드가 있는 클러스터에서 실행하거나, kind e2e 전용 sample에서 "
            "`gpuCount: 0`을 사용하면 Pod 실행 완료까지 검증할 수 있습니다."
        ),
    }


def summarize_job_validation(validation: Any) -> dict[str, Any]:
    if not isinstance(validation, dict):
        return {"present": False, "passed": None, "checks": []}
    checks = []
    for item in validation.get("checks") or []:
        checks.append(
            {
                "name": item.get("name"),
                "expected": item.get("expected"),
                "actual": item.get("actual"),
                "status": item.get("status"),
            }
        )
    return {
        "present": True,
        "passed": validation.get("passed"),
        "checks": checks,
    }


def log_next_actions(summary: dict[str, Any], decision: str) -> list[str]:
    if decision.startswith("succeeded"):
        actions = [
            "현재 로그는 성공 케이스로 보관하고, 데모에서는 Job spec validation 통과와 warning 분류 근거를 함께 보여줍니다.",
            "완전히 스케줄 가능한 kind 데모가 필요하면 e2e sample의 gpuCount를 0으로 둔 별도 sample을 사용합니다.",
        ]
    else:
        actions = [
            "failedStep의 stdout/stderr 로그를 먼저 확인합니다.",
            "관련 profile, RBAC marker, sample YAML을 수정한 뒤 e2e를 clean 모드로 재실행합니다.",
        ]

    project = summary.get("projectDir")
    cluster = summary.get("clusterName")
    sample = summary.get("sample")
    profile = (summary.get("profileConfig") or {}).get("profilePath")
    if project and cluster and sample:
        command = "python3 agent/tools/e2e_runner.py"
        if profile:
            command += f" --profile {profile}"
        command += f" --project {project} --cluster-name {cluster} --sample {sample} --clean --execute"
        actions.append(f"재실행 권장 명령: {command}")
    return actions


def render_log_analysis_report(summary: dict[str, Any]) -> str:
    reasoning = summary["reasoning"]
    lines = [
        "# Agent Log Analysis Report",
        "",
        "## Planner",
        "",
        f"- Requested planner: `{summary.get('planner')}`",
        f"- Effective planner: `{summary.get('effectivePlanner')}`",
        f"- Fallback used: `{summary.get('plannerFallback')}`",
        f"- LLM error: `{summary.get('llmError') or 'none'}`",
        "",
        "## Overall Result",
        "",
        f"- Source log dir: `{summary['sourceLogDir']}`",
        f"- Source analysis: `{summary['sourceAnalysis']}`",
        f"- Decision: `{reasoning['decision']}`",
        f"- Classification: `{reasoning['classification']}`",
        f"- Reason: {reasoning['reason']}",
        "",
        "## Evidence",
        "",
        *[f"- {item}" for item in reasoning["evidence"]],
        "",
        "## Step Summary",
        "",
    ]
    for key, value in reasoning["stepCounts"].items():
        lines.append(f"- {key}: {value}")

    job_validation = reasoning["jobSpecValidation"]
    lines.extend(["", "## Job Spec Validation", ""])
    if job_validation["present"]:
        lines.append(f"- Passed: `{job_validation['passed']}`")
        for item in job_validation["checks"]:
            lines.append(
                f"- {item['name']}: `{item['status']}` "
                f"(expected=`{item['expected']}`, actual=`{item['actual']}`)"
            )
    else:
        lines.append("- Job spec validation was not found in summary.json.")

    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {item}" for item in summary["warnings"]] or ["- none"])

    if summary.get("llmAnalysis"):
        lines.extend(
            [
                "",
                "## LLM Planner Output",
                "",
                "```json",
                json.dumps(summary["llmAnalysis"], indent=2, ensure_ascii=False),
                "```",
            ]
        )

    gpu_explanation = reasoning.get("gpuPendingExplanation") or {}
    if gpu_explanation.get("present"):
        lines.extend(
            [
                "",
                "## GPU Pending Interpretation",
                "",
                f"- {gpu_explanation['message']}",
                f"- Requested GPU count: `{gpu_explanation.get('requestedGpuCount')}`",
                f"- GPU resource name: `{gpu_explanation.get('gpuResourceName')}`",
                f"- Operator/Controller fault: `{gpu_explanation.get('operatorFault')}`",
                f"- Recommended handling: {gpu_explanation.get('recommendedFix')}",
            ]
        )

    lines.extend(["", "## Retrieved Troubleshooting Knowledge", ""])
    for item in summary["retrievedKnowledge"]:
        lines.append(f"- `{item['path']}`: {item['title']}")
        lines.append(f"  - matched: {', '.join(item['matchedKeywords'])}")
        lines.append(f"  - excerpt: {item['excerpt']}")
    if not summary["retrievedKnowledge"]:
        lines.append("- No matching troubleshooting document found.")

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
            *[f"- {item}" for item in reasoning["nextActions"]],
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
