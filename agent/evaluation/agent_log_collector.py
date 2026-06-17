#!/usr/bin/env python3
"""Collect structured facts from Agent execution log directories."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class AgentLogRecord:
    path: Path
    timestamp: str
    mode: str
    agent_mode: str
    requirement: str
    analyze_log: str
    created_at: str
    completed_at: str
    elapsed_seconds: float | None
    tool_results: list[dict[str, Any]]
    validated_tool_calls: list[dict[str, Any]]
    rejected_tool_calls: list[dict[str, Any]]
    generated_files: dict[str, str]
    final_output: dict[str, Any]
    failure_context: dict[str, Any]
    recovery_plan: dict[str, Any]
    local_llm: dict[str, Any]
    rag_mode: str
    fallback_used: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path.relative_to(REPO_ROOT)),
            "timestamp": self.timestamp,
            "mode": self.mode,
            "agentMode": self.agent_mode,
            "requirement": self.requirement,
            "analyzeLog": self.analyze_log,
            "startedAt": timestamp_to_iso(self.timestamp),
            "createdAt": self.created_at,
            "completedAt": self.completed_at,
            "elapsedSeconds": self.elapsed_seconds,
            "validatedToolCalls": self.validated_tool_calls,
            "rejectedToolCalls": self.rejected_tool_calls,
            "toolResults": self.tool_results,
            "generatedFiles": self.generated_files,
            "finalOutput": self.final_output,
            "failureContext": self.failure_context,
            "recoveryPlan": self.recovery_plan,
            "localLLM": self.local_llm,
            "ragMode": self.rag_mode,
            "fallbackUsed": self.fallback_used,
        }


def collect_logs(logs_dir: str | Path | None = None, log_paths: list[str] | None = None) -> list[AgentLogRecord]:
    paths = resolve_log_paths(logs_dir, log_paths)
    return [collect_log(path) for path in paths if (path / "summary.json").is_file()]


def collect_log(path: Path) -> AgentLogRecord:
    summary = read_json(path / "summary.json", {})
    final_output = read_json(path / "final-llm-output.json", {})
    tool_results = read_json(path / "tool-results.json", [])
    validated_tool_calls = read_json(path / "validated-tool-calls.json", [])
    rejected_tool_calls = read_json(path / "rejected-tool-calls.json", [])
    failure_context = read_json(path / "failure-context.json", summary.get("failureContext") or {})
    recovery_plan = read_json(path / "validated-recovery-plan.json", read_json(path / "recovery-plan.json", {}))
    retrieved_docs = read_json(path / "retrieved-docs.json", [])
    created_at = summary.get("createdAt") or timestamp_to_iso(path.name)
    completed_at = created_at or max_file_mtime_iso(path)
    elapsed = elapsed_seconds(timestamp_to_iso(path.name), completed_at)
    return AgentLogRecord(
        path=path,
        timestamp=path.name,
        mode=str(summary.get("mode") or ""),
        agent_mode=str(summary.get("agentMode") or ""),
        requirement=str(summary.get("requirement") or ""),
        analyze_log=str(summary.get("sourceLogDir") or summary.get("logDir") or ""),
        created_at=created_at,
        completed_at=completed_at,
        elapsed_seconds=elapsed,
        tool_results=tool_results if isinstance(tool_results, list) else [],
        validated_tool_calls=validated_tool_calls if isinstance(validated_tool_calls, list) else [],
        rejected_tool_calls=rejected_tool_calls if isinstance(rejected_tool_calls, list) else [],
        generated_files=summary.get("generatedFiles") or {},
        final_output=final_output.get("output") if isinstance(final_output, dict) and isinstance(final_output.get("output"), dict) else final_output,
        failure_context=failure_context if isinstance(failure_context, dict) else {},
        recovery_plan=recovery_plan if isinstance(recovery_plan, dict) else {},
        local_llm=summary.get("localLLM") or final_output.get("localLLM") if isinstance(final_output, dict) else {},
        rag_mode=rag_mode_from_docs(retrieved_docs),
        fallback_used=fallback_used_from_docs(retrieved_docs),
    )


def resolve_log_paths(logs_dir: str | Path | None, log_paths: list[str] | None) -> list[Path]:
    if log_paths:
        return [resolve_path(path) for path in log_paths]
    base = resolve_path(logs_dir or "logs/agent")
    if not base.is_dir():
        return []
    return sorted([path for path in base.iterdir() if path.is_dir() and (path / "summary.json").is_file()])


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def timestamp_to_iso(value: str) -> str:
    match = re.match(r"(\d{8})-(\d{6})", value)
    if not match:
        return ""
    raw = "".join(match.groups())
    dt = datetime.strptime(raw, "%Y%m%d%H%M%S")
    return dt.astimezone().isoformat(timespec="seconds")


def max_file_mtime_iso(path: Path) -> str:
    files = [item for item in path.rglob("*") if item.is_file()]
    if not files:
        return timestamp_to_iso(path.name)
    return datetime.fromtimestamp(max(item.stat().st_mtime for item in files)).astimezone().isoformat(timespec="seconds")


def elapsed_seconds(start: str, end: str) -> float | None:
    try:
        return round((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds(), 3)
    except (TypeError, ValueError):
        return None


def rag_mode_from_docs(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("retrievalMode") or value.get("mode") or "")
    if isinstance(value, list) and value:
        return str(value[0].get("retrievalMode") or "")
    return ""


def fallback_used_from_docs(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(value.get("fallbackUsed"))
    if isinstance(value, list):
        return any(bool(item.get("fallbackUsed")) for item in value if isinstance(item, dict))
    return False


def resolve_path(path: str | Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        value = REPO_ROOT / value
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect Agent log facts.")
    parser.add_argument("--logs-dir", default="logs/agent")
    parser.add_argument("--log-paths", nargs="*")
    args = parser.parse_args()
    records = collect_logs(args.logs_dir, args.log_paths)
    print(json.dumps([record.to_dict() for record in records], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
