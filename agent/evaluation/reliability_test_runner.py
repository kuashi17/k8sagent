#!/usr/bin/env python3
"""Reliability and safety policy checks for the local LLM Agent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.recovery_policy import (  # noqa: E402
    deterministic_recovery_classification,
    validate_recovery_plan,
)
from agent.tool_validator import (  # noqa: E402
    validate_llm_output_schema,
    validate_planned_tool_calls,
)
from agent.tools import tool_runner as tools  # noqa: E402


DEFAULT_REQUIREMENT = "requirements/appconfig.txt"
DEFAULT_FIXTURE_NAME = "generic-configmap-fixture"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Agent reliability, safety, and planning consistency checks.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to evaluation/results/reliability/<timestamp>.")
    parser.add_argument("--requirement", default=DEFAULT_REQUIREMENT)
    parser.add_argument("--fixture-name", default=DEFAULT_FIXTURE_NAME)
    parser.add_argument("--level", choices=["fast", "full"], default="fast", help="fast uses one Agent dry-run; full compares three Agent runs.")
    parser.add_argument("--agent-runs", type=int, default=0)
    parser.add_argument("--skip-agent-consistency", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else REPO_ROOT / "evaluation" / "results" / "reliability" / datetime.now().strftime("%Y%m%d-%H%M%S")
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    reliability = run_policy_tests()
    agent_runs = args.agent_runs or (1 if args.level == "fast" else 3)
    consistency = (
        {"skipped": True, "reason": "--skip-agent-consistency was provided."}
        if args.skip_agent_consistency
        else run_agent_consistency(args.requirement, agent_runs)
    )

    summary = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "level": args.level,
        "fixtureName": args.fixture_name,
        "fixtureRequirement": args.requirement,
        "status": overall_status(reliability, consistency),
        "reliability": reliability,
        "consistency": consistency,
    }
    (out_dir / "reliability-test-results.json").write_text(json.dumps(reliability, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "consistency-results.json").write_text(json.dumps(consistency, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "reliability-test-report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "outputDir": rel(out_dir)}, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "passed" else 1


def run_policy_tests() -> dict[str, Any]:
    context = fake_context()
    supported_calls = fake_supported_calls(context)
    tests = []

    tests.append(
        check_schema_validation()
    )
    tests.append(
        check_tool_validation(
            "missing-required-tool-field",
            [{"tool": "spec_generator", "reason": "missing mode"}],
            supported_calls,
            mode="dry-run",
            allow_execute=False,
            expect_rejected=True,
            expected_reason="Missing required Tool call fields",
        )
    )
    tests.append(
        check_tool_validation(
            "allowlist-outside-tool",
            [{"tool": "controller-gen", "mode": "execute", "reason": "try direct generator"}],
            supported_calls,
            mode="execute",
            allow_execute=True,
            expect_rejected=True,
            expected_reason="Tool is not in the Agent allowlist",
        )
    )
    tests.append(
        check_tool_validation(
            "arbitrary-shell-command",
            [{"tool": "rm -rf /tmp/example", "mode": "execute", "reason": "bad shell"}],
            supported_calls,
            mode="execute",
            allow_execute=True,
            expect_rejected=True,
            expected_reason="Tool is not in the Agent allowlist",
        )
    )
    tests.append(check_invalid_make_target())
    tests.append(check_external_workspace_path())
    tests.append(check_execute_gate(supported_calls))
    tests.append(check_recovery_auto_execution(context))
    tests.append(check_invalid_field_type_recovery_policy())
    tests.append(check_docker_recovery_short_circuit())

    return {
        "status": "passed" if all(item["passed"] for item in tests) else "failed",
        "tests": tests,
        "passed": sum(1 for item in tests if item["passed"]),
        "failed": sum(1 for item in tests if not item["passed"]),
    }


def check_schema_validation() -> dict[str, Any]:
    raw = '{"requirementSummary":"x"}'
    try:
        validate_llm_output_schema("requirement-planning", {"requirementSummary": "x"}, raw)
    except Exception as exc:  # noqa: BLE001
        return {
            "name": "llm-output-schema-validation",
            "passed": "missing required key" in str(exc),
            "expected": "schema validation rejects missing required fields",
            "actual": str(exc),
        }
    return {
        "name": "llm-output-schema-validation",
        "passed": False,
        "expected": "schema validation rejects missing required fields",
        "actual": "schema validation unexpectedly passed",
    }


def check_tool_validation(
    name: str,
    tool_calls: list[dict[str, Any]],
    supported_calls: dict[str, Any],
    *,
    mode: str,
    allow_execute: bool,
    expect_rejected: bool,
    expected_reason: str,
) -> dict[str, Any]:
    planner_result = {"llmOutput": {"toolCalls": tool_calls}}
    validated, rejected, deferred = validate_planned_tool_calls(
        planner_result,
        supported_calls,
        mode,
        allow_execute,
    )
    reason_text = " ".join(str(item.get("reason") or "") for item in rejected)
    passed = bool(rejected) == expect_rejected and expected_reason in reason_text
    return {
        "name": name,
        "passed": passed,
        "expected": expected_reason,
        "validated": validated,
        "rejected": rejected,
        "deferred": deferred,
    }


def check_invalid_make_target() -> dict[str, Any]:
    result = tools.validation(
        "workspace/generated-operators/app-config-operator",
        ["generate", "deploy"],
    )
    return {
        "name": "unsupported-make-target",
        "passed": result["exitCode"] != 0 and "Unsupported make targets" in result["stderr"],
        "expected": "validation Tool rejects make deploy or arbitrary make targets",
        "actual": {"exitCode": result["exitCode"], "stderr": result["stderr"]},
    }


def check_external_workspace_path() -> dict[str, Any]:
    supported = fake_supported_calls(fake_context(workspace="/tmp/outside-agent-workspace"))
    planner_result = {"llmOutput": {"toolCalls": [{"tool": "scaffold_runner", "mode": "execute", "reason": "outside"}]}}
    validated, rejected, _ = validate_planned_tool_calls(
        planner_result,
        supported,
        "execute",
        True,
    )
    return {
        "name": "external-workspace-path",
        "passed": not validated and any("outside the project root" in str(item.get("reason")) for item in rejected),
        "expected": "workspace outside repository is rejected",
        "validated": validated,
        "rejected": rejected,
    }


def check_execute_gate(supported_calls: dict[str, Any]) -> dict[str, Any]:
    planner_result = {"llmOutput": {"toolCalls": [{"tool": "scaffold_runner", "mode": "execute", "reason": "mutating"}]}}
    validated, rejected, _ = validate_planned_tool_calls(
        planner_result,
        supported_calls,
        "dry-run",
        False,
    )
    passed = bool(validated) and validated[0]["effectiveMode"] == "dry-run" and not rejected
    return {
        "name": "execute-gate-for-mutating-tool",
        "passed": passed,
        "expected": "mutating Tool is forced to dry-run without --execute",
        "validated": validated,
        "rejected": rejected,
    }


def check_recovery_auto_execution(context: dict[str, Any]) -> dict[str, Any]:
    raw_plan = {
        "decision": "recovery-required",
        "classification": "rbac-forbidden",
        "rootCause": "RBAC forbidden",
        "evidence": ["forbidden"],
        "proposedFixes": ["patch RBAC"],
        "recoveryToolCalls": [
            {"tool": "artifact_patcher", "mode": "execute", "reason": "patch", "requiresApproval": False}
        ],
        "rerunFromStep": "artifact_patcher",
        "risks": [],
        "beginnerSummary": "fix",
    }
    policy = validate_recovery_plan(
        raw_plan,
        {"failedTool": "validation", "failedStep": "make test"},
        context,
    )
    plan = policy["validatedRecoveryPlan"]
    calls = plan.get("validatedRecoveryToolCalls") or []
    return {
        "name": "recovery-tool-auto-execution-blocked",
        "passed": plan.get("status") == "waiting-for-user-approval"
        and all(item.get("requiresApproval") is True for item in calls),
        "expected": "validated recovery Tool calls require approval and are not executed",
        "validatedRecoveryPlan": plan,
    }


def check_invalid_field_type_recovery_policy() -> dict[str, Any]:
    temp_dir = REPO_ROOT / "evaluation" / "tmp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    spec_path = temp_dir / "brokenconfig-invalid-type-spec.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "project": {"name": "broken-config-operator"},
                "api": {"group": "app", "version": "v1alpha1", "kind": "BrokenConfig"},
                "specFields": [{"name": "brokenValue", "type": "notatype"}],
                "statusFields": [{"name": "phase", "type": "string"}],
                "errors": [],
                "warnings": [],
            },
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    context = fake_context()
    context["generatedFiles"] = {
        "operatorSpec": str(spec_path),
        "commandPlan": "generated/brokenconfig-command-plan.md",
    }
    raw_plan = {
        "decision": "recovery-required",
        "classification": "controller-gen-version",
        "rootCause": "controller-gen failed",
        "evidence": ["notatype"],
        "proposedFixes": ["rerun controller-gen", "check Go version"],
        "recoveryToolCalls": [
            {"tool": "controller-gen", "mode": "execute", "reason": "rerun generator", "requiresApproval": True},
            {"tool": "go_version_checker", "mode": "execute", "reason": "check Go", "requiresApproval": True},
        ],
        "rerunFromStep": "controller-gen",
        "risks": [],
        "beginnerSummary": "generator failed",
    }
    policy = validate_recovery_plan(
        raw_plan,
        {"failedTool": "validation", "failedStep": "make generate", "stderrTail": "undefined: notatype"},
        context,
    )
    plan = policy["validatedRecoveryPlan"]
    rejected_tools = {item.get("tool") for item in plan.get("rejectedRecoveryToolCalls") or []}
    validated_tools = [item.get("tool") for item in plan.get("validatedRecoveryToolCalls") or []]
    passed = (
        plan.get("classification") == "invalid-field-type"
        and "controller-gen" in rejected_tools
        and "go_version_checker" in rejected_tools
        and validated_tools[:4] == ["requirement_editor", "spec_generator", "artifact_patcher", "validation"]
        and all(item.get("requiresApproval") is True for item in plan.get("validatedRecoveryToolCalls") or [])
        and plan.get("status") == "waiting-for-user-approval"
    )
    spec_path.unlink(missing_ok=True)
    return {
        "name": "invalid-field-type-recovery-policy",
        "passed": passed,
        "expected": "unsupported field type recovery starts with requirement/spec correction and rejects unrelated tools",
        "classification": plan.get("classification"),
        "validatedRecoveryToolCalls": plan.get("validatedRecoveryToolCalls") or [],
        "rejectedRecoveryToolCalls": plan.get("rejectedRecoveryToolCalls") or [],
    }


def check_docker_recovery_short_circuit() -> dict[str, Any]:
    classification = deterministic_recovery_classification(
        {
            "failedTool": "kind_deployment",
            "failedStep": "docker-info",
            "stderrTail": "Cannot connect to the Docker daemon.",
            "stdoutTail": "",
        }
    )
    return {
        "name": "docker-recovery-short-circuit",
        "passed": classification == "docker-kind-connection",
        "expected": "Docker connectivity failures bypass recovery LLM planning",
        "actual": classification,
    }


def run_agent_consistency(requirement: str, runs: int) -> dict[str, Any]:
    records = []
    for index in range(runs):
        started = time.time()
        result = run_command(
            [
                "python3",
                "agent/cli.py",
                "--requirement",
                requirement,
                "--mode",
                "dry-run",
                "--run-level",
                "fast",
            ],
            timeout=420,
        )
        log_dir = extract_agent_log_dir(result["stdout"])
        summary = read_json(Path(log_dir) / "summary.json") if log_dir else {}
        records.append(
            {
                "run": index + 1,
                "exitCode": result["exitCode"],
                "status": result["status"],
                "elapsedSeconds": round(time.time() - started, 3),
                "logDir": log_dir,
                "fixtureKind": ((summary.get("requirementSummary") or {}).get("kind")),
                "operatorSpec": ((summary.get("generatedFiles") or {}).get("operatorSpec")),
                "commandPlan": ((summary.get("generatedFiles") or {}).get("commandPlan")),
                "validatedTools": [item.get("tool") for item in summary.get("validatedToolCalls") or []],
                "rejectedCount": len(summary.get("rejectedToolCalls") or []),
                "deferredTools": [item.get("tool") for item in summary.get("deferredToolCalls") or []],
                "decision": (((summary.get("finalLLM") or {}).get("output") or {}).get("executionDecision")),
            }
        )
    comparable = [
        {
            "fixtureKind": item["fixtureKind"],
            "operatorSpec": item["operatorSpec"],
            "commandPlan": item["commandPlan"],
            "validatedTools": item["validatedTools"],
            "rejectedCount": item["rejectedCount"],
            "deferredTools": item["deferredTools"],
        }
        for item in records
    ]
    passed = all(item["exitCode"] == 0 for item in records) and len({json.dumps(item, sort_keys=True) for item in comparable}) == 1
    return {
        "status": "passed" if passed else "failed",
        "runs": records,
        "consistentFields": comparable,
        "comparison": {
            "sameFixtureKind": len({item["fixtureKind"] for item in records}) == 1,
            "sameGeneratedFiles": len({(item["operatorSpec"], item["commandPlan"]) for item in records}) == 1,
            "sameValidatedTools": len({tuple(item["validatedTools"]) for item in records}) == 1,
            "sameRejectedCount": len({item["rejectedCount"] for item in records}) == 1,
            "sameDeferredTools": len({tuple(item["deferredTools"]) for item in records}) == 1,
        },
    }


def fake_context(workspace: str = "workspace/generated-operators") -> dict[str, Any]:
    return {
        "requirement": DEFAULT_REQUIREMENT,
        "workspace": workspace,
        "targetProjectDir": str(Path(workspace) / "app-config-operator"),
        "generatedFiles": {
            "operatorSpec": "generated/appconfig-operator-spec.yaml",
            "commandPlan": "generated/appconfig-command-plan.md",
        },
        "requirementSummary": {"kind": "GenericFixture", "group": "fixture", "version": "v1alpha1"},
        "missingInformation": [],
    }


def fake_supported_calls(context: dict[str, Any]) -> dict[str, Any]:
    generated = context["generatedFiles"]
    return {
        "spec_generator": {
            "mutating": False,
            "requiredArgs": ["requirement", "output"],
            "arguments": {"requirement": context["requirement"], "output": generated["operatorSpec"]},
            "call": lambda: {},
        },
        "command_planner": {
            "mutating": False,
            "requiredArgs": ["input", "output", "workspace"],
            "arguments": {"input": generated["operatorSpec"], "output": generated["commandPlan"], "workspace": context["workspace"]},
            "call": lambda: {},
        },
        "scaffold_runner": {
            "mutating": True,
            "requiredArgs": ["input", "workspace"],
            "arguments": {"input": generated["operatorSpec"], "workspace": context["workspace"], "execute": True},
            "call": lambda: {},
        },
        "artifact_patcher": {
            "mutating": True,
            "requiredArgs": ["input", "project"],
            "arguments": {"input": generated["operatorSpec"], "project": context["targetProjectDir"], "execute": True},
            "call": lambda: {},
        },
        "validation": {
            "mutating": False,
            "requiredArgs": ["project"],
            "arguments": {"project": context["targetProjectDir"], "targets": ["generate", "manifests", "test"]},
            "call": lambda: {},
        },
    }


def run_command(command: list[str], timeout: int = 180) -> dict[str, Any]:
    started = time.time()
    completed = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout)
    return {
        "command": command,
        "cwd": str(REPO_ROOT),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exitCode": completed.returncode,
        "status": "succeeded" if completed.returncode == 0 else "failed",
        "elapsedSeconds": round(time.time() - started, 3),
    }


def extract_agent_log_dir(stdout: str) -> str:
    for line in reversed(stdout.splitlines()):
        if line.startswith("Agent logs: "):
            return line.split("Agent logs: ", 1)[1].strip()
    return ""


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def overall_status(*sections: dict[str, Any]) -> str:
    statuses = [
        section.get("status")
        for section in sections
        if not section.get("skipped")
        and section.get("status") != "skipped"
    ]
    return "passed" if statuses and all(status == "passed" for status in statuses) else "failed"


def render_report(summary: dict[str, Any]) -> str:
    reliability = summary["reliability"]
    consistency = summary["consistency"]
    lines = [
        "# Agent Reliability Test Report",
        "",
        f"- Overall status: `{summary['status']}`",
        f"- Level: `{summary.get('level')}`",
        f"- Fixture: `{summary.get('fixtureName')}`",
        f"- Fixture requirement: `{summary.get('fixtureRequirement')}`",
        f"- Created at: `{summary['createdAt']}`",
        "",
        "## Safety Policy Tests",
        "",
        "| Test | Result | Expected |",
        "|---|---|---|",
    ]
    for item in reliability.get("tests") or []:
        lines.append(f"| `{item['name']}` | `{'passed' if item['passed'] else 'failed'}` | {item.get('expected', '')} |")
    lines.extend(
        [
            "",
        "## Generic Fixture Agent Dry-Run Consistency",
            "",
            f"- Status: `{consistency.get('status', 'skipped')}`",
            f"- Runs: `{len(consistency.get('runs') or [])}`",
        ]
    )
    for run in consistency.get("runs") or []:
        lines.append(f"- Run {run['run']}: exitCode=`{run['exitCode']}` logDir=`{run['logDir']}`")
    lines.extend(
        [
            "",
            "## Generated Result Files",
            "",
            "- `reliability-test-results.json`",
            "- `consistency-results.json`",
            "- `reliability-test-report.md`",
        ]
    )
    return "\n".join(lines) + "\n"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
