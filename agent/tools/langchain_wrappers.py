#!/usr/bin/env python3
"""Tool wrappers used by the LangChain-style Agent orchestrator.

The wrappers intentionally call the existing CLI tools with subprocess.
This keeps the current automation pipeline stable while exposing each step
as a tool-like function that an Agent planner can select and sequence.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

try:  # Optional dependency for future real LangChain Agent execution.
    from langchain_core.tools import Tool
except ImportError:  # pragma: no cover - optional dependency is not required for CLI wrapping.
    Tool = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[2]


def run_command(command: list[str], cwd: Path | None = None) -> dict[str, Any]:
    """Run a command and return a serializable result object.

    Failures are returned as data instead of being raised so the orchestrator
    can summarize partial progress and recommend a next action.
    """

    workdir = cwd or REPO_ROOT
    completed = subprocess.run(command, cwd=workdir, text=True, capture_output=True)
    return {
        "command": command,
        "cwd": str(workdir),
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exitCode": completed.returncode,
        "status": "succeeded" if completed.returncode == 0 else "failed",
    }


def spec_generator(requirement: str, output: str | None = None) -> dict[str, Any]:
    command = ["python3", "agent/tools/spec_generator.py", requirement]
    if output:
        command.extend(["--output", output])
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
    profile: str | None = None,
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
    if profile:
        command.extend(["--profile", profile])
    command.append("--execute" if execute else "--dry-run")
    return run_command(command)


def e2e_runner(
    input_spec: str | None = None,
    profile: str | None = None,
    project: str | None = None,
    cluster_name: str | None = None,
    sample: str | None = None,
    *,
    clean: bool = False,
    delete_pvc: bool = False,
    execute: bool = False,
) -> dict[str, Any]:
    command = ["python3", "agent/tools/e2e_runner.py"]
    if input_spec:
        command.extend(["--input", input_spec])
    if profile:
        command.extend(["--profile", profile])
    if project:
        command.extend(["--project", project])
    if cluster_name:
        command.extend(["--cluster-name", cluster_name])
    if sample:
        command.extend(["--sample", sample])
    if clean:
        command.append("--clean")
    if delete_pvc:
        command.append("--delete-pvc")
    command.append("--execute" if execute else "--dry-run")
    return run_command(command)


def kind_deployment_runner(
    project: str,
    *,
    cluster_name: str,
    image: str,
    sample: str,
    namespace: str,
    deployment: str,
    validator: str,
    validator_config: dict[str, Any],
    execute: bool = False,
    skip_lifecycle: bool = False,
    skip_prepare_controller: bool = False,
    skip_prevalidation: bool = False,
) -> dict[str, Any]:
    command = [
        "python3",
        "agent/tools/kind_deployment_runner.py",
        "--project",
        project,
        "--cluster-name",
        cluster_name,
        "--image",
        image,
        "--sample",
        sample,
        "--namespace",
        namespace,
        "--deployment",
        deployment,
        "--validator",
        validator,
        "--validator-config",
        json.dumps(validator_config, ensure_ascii=False),
    ]
    if skip_lifecycle:
        command.append("--skip-lifecycle")
    if skip_prepare_controller:
        command.append("--skip-prepare-controller")
    if skip_prevalidation:
        command.append("--skip-prevalidation")
    if not execute:
        command.append("--dry-run")
    result = run_command(command)
    try:
        result["deploymentSummary"] = json.loads(result.get("stdout") or "{}")
    except json.JSONDecodeError:
        result["deploymentSummary"] = {}
    return result


def validation(project: str, targets: list[str] | None = None) -> dict[str, Any]:
    allowed = ["generate", "manifests", "test"]
    requested = targets or allowed
    invalid = [target for target in requested if target not in allowed]
    if invalid:
        return {
            "command": ["make", *requested],
            "cwd": str(REPO_ROOT / project),
            "stdout": "",
            "stderr": "Unsupported make targets: " + ", ".join(invalid),
            "exitCode": 2,
            "status": "failed",
            "steps": [],
        }

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
    return {
        "command": ["make", *requested],
        "cwd": str(REPO_ROOT / project),
        "stdout": stdout,
        "stderr": stderr,
        "exitCode": exit_code,
        "status": "succeeded" if exit_code == 0 else "failed",
        "steps": results,
    }


def log_analyzer(log_dir: str, output: str | None = None) -> dict[str, Any]:
    command = ["python3", "agent/tools/log_analyzer.py", "--log-dir", log_dir]
    if output:
        command.extend(["--output", output])
    return run_command(command)


def as_langchain_tools() -> list[Any]:
    """Return LangChain Tool objects when langchain-core is installed.

    The current Agent orchestrator calls these Python functions directly.
    This adapter makes the same wrappers usable by a future LangChain ReAct/tool-calling
    Agent without changing the existing CLI tools.
    """

    if Tool is None:
        return []
    return [
        Tool.from_function(
            name="spec_generator",
            description="Convert a natural language Operator requirement file into operator-spec.yaml.",
            func=lambda requirement: spec_generator(requirement),
        ),
        Tool.from_function(
            name="command_planner",
            description="Create a Kubebuilder command plan from an operator spec path.",
            func=lambda input_spec: command_planner(input_spec, default_command_plan_path(input_spec)),
        ),
        Tool.from_function(
            name="scaffold_runner_dry_run",
            description="Show Kubebuilder scaffold commands without executing them.",
            func=lambda input_spec: scaffold_runner(input_spec),
        ),
    ]


def default_command_plan_path(input_spec: str) -> str:
    path = Path(input_spec)
    name = path.name.replace("-operator-spec.yaml", "-command-plan.md")
    return str(path.with_name(name))
