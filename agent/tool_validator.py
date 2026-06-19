"""LLM output and planned Tool call validation for the Agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agent.contracts import LLM_OUTPUT_CONTRACTS
from agent.llm.planner import LLMOutputParseError


LLM_OUTPUT_SCHEMAS = {
    "requirement-planning": {
        "requirementSummary": str,
        "missingInformation": list,
        "recommendedProfile": str,
        "plannedSteps": list,
        "toolCalls": list,
        "risks": list,
        "nextActions": list,
    },
    "log-analysis": {
        "decision": str,
        "classification": str,
        "rootCause": str,
        "evidence": list,
        "recommendedFixes": list,
        "rerunCommand": str,
        "explanationForBeginner": str,
    },
    "tool-result-evaluation": {
        "executionDecision": str,
        "completedSteps": list,
        "failedSteps": list,
        "generatedArtifacts": list,
        "validationResults": dict,
        "evidence": list,
        "warnings": list,
        "recommendedNextActions": list,
        "beginnerSummary": str,
    },
    "recovery-planning": {
        "decision": str,
        "classification": str,
        "rootCause": str,
        "evidence": list,
        "proposedFixes": list,
        "recoveryToolCalls": list,
        "rerunFromStep": str,
        "risks": list,
        "beginnerSummary": str,
    },
}


def validate_llm_output_schema(mode: str, output: dict[str, Any], raw: str) -> None:
    contract = LLM_OUTPUT_CONTRACTS.get(mode)
    if contract:
        try:
            contract.model_validate(output)
        except ValidationError as exc:
            errors = []
            for item in exc.errors():
                location = ".".join(str(part) for part in item["loc"])
                if item["type"] == "missing":
                    errors.append(f"missing required key: {location}")
                else:
                    errors.append(f"{location}: {item['msg']}")
            raise LLMOutputParseError(
                f"LLM JSON schema validation failed for {mode}: "
                + "; ".join(errors),
                raw,
            ) from exc
        return
    schema = LLM_OUTPUT_SCHEMAS.get(mode)
    if not schema:
        return
    errors = []
    for key, expected_type in schema.items():
        if key not in output:
            errors.append(f"missing required key: {key}")
            continue
        if not isinstance(output[key], expected_type):
            errors.append(
                f"invalid type for {key}: expected {expected_type.__name__}, got {type(output[key]).__name__}"
            )
    if mode == "requirement-planning" and isinstance(output.get("toolCalls"), list):
        for index, item in enumerate(output["toolCalls"]):
            if not isinstance(item, dict):
                errors.append(f"toolCalls[{index}] must be an object")
                continue
            for key in ("tool", "mode"):
                if not item.get(key):
                    errors.append(f"toolCalls[{index}] missing required key: {key}")
    if errors:
        raise LLMOutputParseError(f"LLM JSON schema validation failed for {mode}: {'; '.join(errors)}", raw)


def validate_planned_tool_calls(
    planner_result: dict[str, Any],
    supported_calls: dict[str, Any],
    mode: str,
    allow_execute: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    output = planner_result.get("llmOutput") or {}
    requested = output.get("toolCalls") if isinstance(output, dict) else None
    if not isinstance(requested, list):
        return [], [{"tool": "", "reason": "LLM output did not include a toolCalls list.", "raw": requested}], []

    validated: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in requested:
        if not isinstance(item, dict):
            rejected.append({"tool": "", "reason": "Tool call is not a JSON object.", "raw": item})
            continue
        missing_tool_call_keys = [key for key in ("tool", "mode") if not item.get(key)]
        if missing_tool_call_keys:
            rejected.append(
                {
                    "tool": str(item.get("tool") or ""),
                    "reason": "Missing required Tool call fields: " + ", ".join(missing_tool_call_keys),
                    "raw": item,
                }
            )
            continue
        tool_name = normalize_tool_name(str(item.get("tool") or ""))
        requested_mode = normalize_tool_mode(str(item.get("mode") or "dry-run"), mode)
        if tool_name not in supported_calls:
            rejected.append({"tool": tool_name, "reason": "Tool is not in the Agent allowlist.", "raw": item})
            continue
        if mode == "dry-run" and tool_name in {"artifact_patcher", "validation"}:
            deferred.append(
                {
                    "tool": tool_name,
                    "reason": "Deferred in Agent dry-run because this Tool requires a scaffolded project directory.",
                    "raw": item,
                }
            )
            continue
        if tool_name in seen:
            rejected.append({"tool": tool_name, "reason": "Duplicate Tool call was skipped.", "raw": item})
            continue
        if requested_mode not in {"generate", "dry-run", "execute"}:
            rejected.append({"tool": tool_name, "reason": f"Unsupported mode: {requested_mode}", "raw": item})
            continue
        seen.add(tool_name)
        spec = supported_calls[tool_name]
        arguments = dict(spec["arguments"])
        missing = [name for name in spec["requiredArgs"] if arguments.get(name) in (None, "")]
        if missing:
            rejected.append({"tool": tool_name, "reason": "Missing required arguments: " + ", ".join(missing), "raw": item})
            continue
        path_error = validate_tool_paths(tool_name, arguments)
        if path_error:
            rejected.append({"tool": tool_name, "reason": path_error, "raw": item})
            continue
        effective_mode = "execute" if spec["mutating"] and mode == "execute" and allow_execute else requested_mode
        if spec["mutating"] and not allow_execute:
            effective_mode = "dry-run"
        validated.append(
            {
                "tool": tool_name,
                "requestedMode": requested_mode,
                "effectiveMode": effective_mode,
                "reason": item.get("reason") or "",
                "arguments": arguments,
                "mutating": bool(spec["mutating"]),
                "executeAllowed": bool(allow_execute),
            }
        )
    return validated, rejected, deferred


def planned_tool_calls(
    planner_result: dict[str, Any],
    supported_calls: dict[str, Any],
) -> list[tuple[str, Any]]:
    validated, _, _ = validate_planned_tool_calls(planner_result, supported_calls, "dry-run", False)
    return [(item["tool"], supported_calls[item["tool"]]) for item in validated]


def normalize_tool_name(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "scaffold": "scaffold_runner",
        "scaffold_runner_dry_run": "scaffold_runner",
        "patch": "artifact_patcher",
        "artifact_patch": "artifact_patcher",
        "validate": "validation",
        "make": "validation",
        "make_generate": "validation",
        "make_manifests": "validation",
        "make_test": "validation",
    }
    return aliases.get(normalized, normalized)


def normalize_tool_mode(value: str, agent_mode: str) -> str:
    normalized = value.strip().lower()
    if "|" in normalized:
        options = {part.strip() for part in normalized.split("|")}
        if agent_mode == "execute" and "execute" in options:
            return "execute"
        if "dry-run" in options:
            return "dry-run"
    aliases = {
        "dry_run": "dry-run",
        "dryrun": "dry-run",
        "plan": "dry-run",
        "generate": "generate",
        "execute": "execute",
    }
    return aliases.get(normalized, normalized)


def validate_tool_paths(tool_name: str, arguments: dict[str, Any]) -> str:
    for key in ("workspace", "project"):
        value = arguments.get(key)
        if value and not is_inside_repo(Path(str(value))):
            return f"{key} path is outside the project root: {value}"
    if tool_name == "validation":
        targets = arguments.get("targets") or []
        invalid = [target for target in targets if target not in {"generate", "manifests", "test"}]
        if invalid:
            return "Unsupported validation targets: " + ", ".join(str(item) for item in invalid)
    return ""


def is_inside_repo(path: Path, root: Path | None = None) -> bool:
    project_root = (root or Path.cwd()).resolve()
    resolved = (project_root / path).resolve() if not path.is_absolute() else path.resolve()
    try:
        resolved.relative_to(project_root)
        return True
    except ValueError:
        return False
