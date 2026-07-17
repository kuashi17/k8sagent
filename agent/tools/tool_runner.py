#!/usr/bin/env python3
"""Run the approved Agent tools through stable subprocess boundaries.

The planner selects a registered tool name, while this module owns the exact
CLI command that is executed. Keeping command construction here prevents an
LLM response from becoming an arbitrary shell command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from agent.error_taxonomy import normalize_tool_result


REPO_ROOT = Path(__file__).resolve().parents[2]


def run_command(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    """Run a command and return a serializable result object.

    Failures are returned as data instead of being raised so the orchestrator
    can summarize partial progress and recommend a next action.
    """

    workdir = cwd or REPO_ROOT
    completed = subprocess.run(command, cwd=workdir, text=True, capture_output=True)
    return normalize_tool_result({
        "command": command,
        "cwd": str(workdir),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exitCode": completed.returncode,
        "status": "succeeded" if completed.returncode == 0 else "failed",
    })


def spec_generator(requirement: str, output: str | None = None) -> dict[str, Any]:
    command = ["python3", "agent/tools/spec_generator.py", requirement]
    if output:
        command.extend(["--output", output])
    return run_command(command)


def capability_drafter(
    input_spec: str,
    output: str,
    *,
    approve: bool = False,
    approved_proposal: str = "",
    approval_digest: str = "",
) -> dict[str, Any]:
    command = [
        "python3",
        "agent/tools/capability_drafter.py",
        "--input",
        input_spec,
        "--output",
        output,
    ]
    if approve:
        command.extend(
            [
                "--approve",
                "--execute",
                "--approve-proposal",
                approved_proposal,
                "--approval-digest",
                approval_digest,
            ]
        )
    return run_command(command)


def command_planner(input_spec: str, output: str, workspace: str = "workspace/generated-operators") -> dict[str, Any]:
    command = [
        "python3",
        "agent/tools/command_planner.py",
        "--input",
        input_spec,
        "--output",
        output,
        "--workspace",
        workspace,
    ]
    return run_command(command)


def scaffold_runner(
    input_spec: str,
    workspace: str = "workspace/generated-operators",
    *,
    execute: bool = False,
    preflight: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    command = [
        "python3",
        "agent/tools/scaffold_runner.py",
        "--input",
        input_spec,
        "--workspace",
        workspace,
    ]
    if preflight:
        command.append("--preflight")
    elif execute:
        command.append("--execute")
    else:
        command.append("--dry-run")
    if force:
        command.append("--force")
    return run_command(command)


def artifact_patcher(
    input_spec: str,
    project: str,
    *,
    execute: bool = False,
) -> dict[str, Any]:
    command = [
        "python3",
        "agent/tools/artifact_patcher.py",
        "--input",
        input_spec,
        "--project",
        project,
    ]
    command.append("--execute" if execute else "--dry-run")
    return run_command(command)


def validation(project: str, targets: list[str] | None = None) -> dict[str, Any]:
    allowed = ["generate", "manifests", "test"]
    requested = targets or allowed
    invalid = [target for target in requested if target not in allowed]
    if invalid:
        return normalize_tool_result({
            "command": ["make", *requested],
            "cwd": str(REPO_ROOT / project),
            "stdout": "",
            "stderr": "Unsupported make targets: " + ", ".join(invalid),
            "exitCode": 2,
            "status": "failed",
            "steps": [],
        }, "validation")

    results = []
    for target in requested:
        result = run_command(["make", target], cwd=REPO_ROOT / project)
        result["target"] = target
        results.append(result)
        if result["exitCode"] != 0:
            break

    stdout = "\n".join(f"## make {item['target']}\n{item['stdout']}" for item in results)
    stderr = "\n".join(f"## make {item['target']}\n{item['stderr']}" for item in results if item.get("stderr"))
    exit_code = results[-1]["exitCode"] if results else 0
    return normalize_tool_result({
        "command": ["make", *requested],
        "cwd": str(REPO_ROOT / project),
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": exit_code,
        "status": "succeeded" if exit_code == 0 else "failed",
        "steps": results,
    }, "validation")


def log_analyzer(log_dir: str, output: str | None = None) -> dict[str, Any]:
    command = ["python3", "agent/tools/log_analyzer.py", "--log-dir", log_dir]
    if output:
        command.extend(["--output", output])
    return run_command(command)
