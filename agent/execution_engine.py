"""Tool capability construction and ordered execution for Agent plans."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agent.contracts import ExecutionResult, ToolResult
from agent.tool_validator import validate_planned_tool_calls
from agent.tools import langchain_wrappers as tools


TOOL_ORDER = {
    "spec_generator": 10,
    "command_planner": 20,
    "scaffold_runner": 30,
    "artifact_patcher": 40,
    "validation": 50,
    "e2e_runner": 60,
    "kind_deployment": 70,
}


def execute_planned_tools(
    context: dict[str, Any],
    mode: str,
    allow_execute: bool,
    planner_result: dict[str, Any],
) -> dict[str, Any]:
    supported_calls = build_supported_calls(context, mode, allow_execute)
    validation_started = time.perf_counter()
    validated, rejected, deferred = validate_planned_tool_calls(
        planner_result,
        supported_calls,
        mode,
        allow_execute,
    )
    validated, resume_deferred = apply_resume_policy(validated, context)
    deferred.extend(resume_deferred)
    validated = order_validated_tool_calls(validated)
    tool_validation_seconds = elapsed(validation_started)
    if not validated:
        print("\nLLM planner did not request any supported Tool calls.")
        return execution_result(
            validated,
            rejected,
            deferred,
            [],
            tool_validation_seconds,
            0.0,
        )

    execution_started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for item in validated:
        name = item["tool"]
        print(f"\nCalling tool: {name}")
        result = supported_calls[name]["call"]()
        result["tool"] = name
        result = ToolResult.model_validate(result).to_dict()
        results.append(result)
        print(f"exitCode={result['exitCode']} status={result['status']}")
        if result["exitCode"] != 0:
            break
    return execution_result(
        validated,
        rejected,
        deferred,
        results,
        tool_validation_seconds,
        elapsed(execution_started),
    )


def build_supported_calls(
    context: dict[str, Any],
    mode: str,
    allow_execute: bool,
) -> dict[str, dict[str, Any]]:
    generated = context["generatedFiles"]
    mutating_execute = mode == "execute" and allow_execute
    selected_profile = context.get("selectedProfile") or {}
    profile_path = selected_profile.get("path")
    supported_calls: dict[str, dict[str, Any]] = {
        "spec_generator": {
            "mutating": False,
            "requiredArgs": ["requirement", "output"],
            "arguments": {"requirement": context["requirement"], "output": generated["operatorSpec"]},
            "call": lambda: tools.spec_generator(context["requirement"], generated["operatorSpec"]),
        },
        "command_planner": {
            "mutating": False,
            "requiredArgs": ["input", "output", "workspace"],
            "arguments": {
                "input": generated["operatorSpec"],
                "output": generated["commandPlan"],
                "workspace": context["workspace"],
            },
            "call": lambda: tools.command_planner(
                generated["operatorSpec"],
                generated["commandPlan"],
                context["workspace"],
            ),
        },
        "scaffold_runner": {
            "mutating": True,
            "requiredArgs": ["input", "workspace"],
            "arguments": {
                "input": generated["operatorSpec"],
                "workspace": context["workspace"],
                "execute": mutating_execute,
            },
            "call": lambda: tools.scaffold_runner(
                generated["operatorSpec"],
                context["workspace"],
                execute=mutating_execute,
            ),
        },
        "artifact_patcher": {
            "mutating": True,
            "requiredArgs": ["input", "project"],
            "arguments": {
                "input": generated["operatorSpec"],
                "project": context["targetProjectDir"],
                "profile": profile_path,
                "execute": mutating_execute,
            },
            "call": lambda: tools.artifact_patcher(
                generated["operatorSpec"],
                context["targetProjectDir"],
                profile_path,
                execute=mutating_execute,
            ),
        },
        "validation": {
            "mutating": False,
            "requiredArgs": ["project"],
            "arguments": {
                "project": context["targetProjectDir"],
                "targets": ["generate", "manifests", "test"],
            },
            "call": lambda: tools.validation(
                context["targetProjectDir"],
                ["generate", "manifests", "test"],
            ),
        },
        "e2e_runner": {
            "mutating": True,
            "requiredArgs": ["input"],
            "arguments": {
                "input": generated["operatorSpec"],
                "profile": profile_path,
                "execute": mutating_execute,
            },
            "call": lambda: tools.e2e_runner(
                generated["operatorSpec"],
                profile_path,
                execute=mutating_execute,
            ),
        },
    }
    kind_deployment = selected_profile.get("kindDeployment") or {}
    if context.get("kindDeploymentRequested") and kind_deployment.get("enabled"):
        supported_calls["kind_deployment"] = build_kind_deployment_call(
            context,
            kind_deployment,
            mutating_execute,
        )
    return supported_calls


def build_kind_deployment_call(
    context: dict[str, Any],
    capability: dict[str, Any],
    execute: bool,
) -> dict[str, Any]:
    project = capability.get("project") or context["targetProjectDir"]
    arguments = {
        "project": project,
        "clusterName": capability.get("clusterName"),
        "image": capability.get("image"),
        "sample": capability.get("sample"),
        "namespace": capability.get("namespace"),
        "deployment": capability.get("deployment"),
        "validator": capability.get("validator"),
        "validatorConfig": capability.get("validatorConfig") or {},
        "execute": execute,
    }
    return {
        "mutating": True,
        "requiredArgs": [
            "project",
            "clusterName",
            "image",
            "sample",
            "namespace",
            "deployment",
            "validator",
            "validatorConfig",
        ],
        "arguments": arguments,
        "call": lambda: tools.kind_deployment_runner(
            str(project),
            cluster_name=str(capability.get("clusterName") or ""),
            image=str(capability.get("image") or ""),
            sample=str(capability.get("sample") or ""),
            namespace=str(capability.get("namespace") or ""),
            deployment=str(capability.get("deployment") or ""),
            validator=str(capability.get("validator") or ""),
            validator_config=capability.get("validatorConfig") or {},
            execute=execute,
            skip_prepare_controller=bool(capability.get("skipPrepareController")),
            skip_prevalidation=bool(capability.get("skipPrevalidation")),
        ),
    }


def apply_resume_policy(
    validated: list[dict[str, Any]],
    context: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not context.get("resumeExisting") or not Path(context["targetProjectDir"]).is_dir():
        return validated, []
    resumed = [item for item in validated if item.get("tool") == "scaffold_runner"]
    remaining = [item for item in validated if item.get("tool") != "scaffold_runner"]
    deferred = [
        {
            "tool": "scaffold_runner",
            "reason": "Skipped because --resume-existing was provided and the target project already exists.",
            "raw": item,
        }
        for item in resumed
    ]
    return remaining, deferred


def order_validated_tool_calls(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(calls, key=lambda item: TOOL_ORDER.get(str(item.get("tool")), 999))


def execution_result(
    validated: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    deferred: list[dict[str, Any]],
    results: list[dict[str, Any]],
    validation_seconds: float,
    execution_seconds: float,
) -> dict[str, Any]:
    return ExecutionResult.model_validate(
        {
            "validatedToolCalls": validated,
            "rejectedToolCalls": rejected,
            "deferredToolCalls": deferred,
            "toolResults": results,
            "timings": {
                "toolValidationSeconds": validation_seconds,
                "toolExecutionSeconds": execution_seconds,
            },
        }
    ).to_dict()


def elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 3)
