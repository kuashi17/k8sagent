"""Build bounded failure evidence for recovery planning."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def detect_failure_context(
    context: dict[str, Any],
    execution: dict[str, list[dict[str, Any]]],
    mode: str,
) -> dict[str, Any] | None:
    if execution["rejectedToolCalls"]:
        rejected = json.dumps(execution["rejectedToolCalls"], ensure_ascii=False)
        return {
            "failedTool": "tool-validation",
            "failedStep": "rejectedToolCalls",
            "exitCode": 2,
            "command": [],
            "stdoutTail": "",
            "stderrTail": rejected,
            "generatedArtifacts": existing_artifacts(context),
            "missingArtifacts": missing_artifacts(context),
            "previousSuccessfulSteps": successful_step_names(execution["toolResults"]),
            "workspace": context["workspace"],
            "targetProjectDir": context["targetProjectDir"],
            "failedResult": {
                "tool": "tool-validation",
                "exitCode": 2,
                "status": "failed",
                "stderr": rejected,
            },
        }

    for result in execution["toolResults"]:
        if result.get("exitCode") == 0:
            continue
        failed_step = (
            (result.get("deploymentSummary") or {}).get("failedStep")
            or failed_validation_step(result)
        )
        return {
            "failedTool": result.get("tool"),
            "failedStep": failed_step or result.get("tool"),
            "exitCode": result.get("exitCode"),
            "command": result.get("command"),
            "stdoutTail": tail_lines(str(result.get("stdout") or ""), 100),
            "stderrTail": tail_lines(str(result.get("stderr") or ""), 100),
            "generatedArtifacts": existing_artifacts(context),
            "missingArtifacts": missing_artifacts(context),
            "previousSuccessfulSteps": successful_step_names(
                execution["toolResults"],
                stop_at=result.get("tool"),
            ),
            "workspace": context["workspace"],
            "targetProjectDir": context["targetProjectDir"],
            "agentMode": mode,
            "failedResult": result,
        }

    missing = missing_artifacts(context)
    if mode != "execute" or not missing:
        return None
    message = "Missing expected artifacts: " + ", ".join(missing)
    return {
        "failedTool": "artifact-check",
        "failedStep": "expected artifact missing",
        "exitCode": 2,
        "command": [],
        "stdoutTail": "",
        "stderrTail": message,
        "generatedArtifacts": existing_artifacts(context),
        "missingArtifacts": missing,
        "previousSuccessfulSteps": successful_step_names(execution["toolResults"]),
        "workspace": context["workspace"],
        "targetProjectDir": context["targetProjectDir"],
        "agentMode": mode,
        "failedResult": {
            "tool": "artifact-check",
            "exitCode": 2,
            "status": "failed",
            "stderr": message,
        },
    }


def failed_validation_step(result: dict[str, Any]) -> str:
    if result.get("tool") != "validation":
        return ""
    for step in result.get("steps") or []:
        if step.get("exitCode") != 0:
            return f"make {step.get('target')}"
    return "validation"


def successful_step_names(
    results: list[dict[str, Any]],
    stop_at: str | None = None,
) -> list[str]:
    names = []
    for item in results:
        if stop_at and item.get("tool") == stop_at:
            break
        if item.get("exitCode") == 0 and item.get("tool"):
            names.append(str(item["tool"]))
    return names


def expected_artifacts(context: dict[str, Any]) -> list[str]:
    target = Path(context["targetProjectDir"])
    summary = context["requirementSummary"]
    kind = summary.get("kind") or ""
    version = summary.get("version") or "v1alpha1"
    group = summary.get("group") or ""
    lower_kind = kind.lower()
    return [
        context["generatedFiles"]["operatorSpec"],
        context["generatedFiles"]["commandPlan"],
        str(target / "api" / version / f"{lower_kind}_types.go"),
        str(target / "config" / "crd"),
        str(target / "config" / "rbac" / "role.yaml"),
        str(target / "config" / "samples" / f"{group}_{version}_{lower_kind}.yaml"),
    ]


def existing_artifacts(context: dict[str, Any]) -> list[str]:
    return [path for path in expected_artifacts(context) if Path(path).exists()]


def missing_artifacts(context: dict[str, Any]) -> list[str]:
    return [path for path in expected_artifacts(context) if not Path(path).exists()]


def tail_lines(text: str, count: int) -> str:
    return "\n".join(text.splitlines()[-count:])


def build_failure_rag_query(failure_context: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Kubebuilder Operator failure recovery",
            str(failure_context.get("failedTool") or ""),
            str(failure_context.get("failedStep") or ""),
            str(failure_context.get("exitCode") or ""),
            str(failure_context.get("stdoutTail") or ""),
            str(failure_context.get("stderrTail") or ""),
        ]
    )
