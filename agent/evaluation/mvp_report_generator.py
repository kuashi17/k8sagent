#!/usr/bin/env python3
"""Generate Markdown reports for MVP evaluation metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_report(summary: dict[str, Any], details: dict[str, Any]) -> str:
    rows = [
        ("작업 시간 단축", "timeReduction"),
        ("산출물 완성도", "artifactCompletion"),
        ("1차 검증 통과율", "firstPassValidation"),
        ("오류 대응 속도", "errorResponse"),
    ]
    lines = [
        "# MVP Evaluation Report",
        "",
        f"- Generated At: {summary.get('generatedAt')}",
        f"- Baseline Source: {summary.get('baseline', {}).get('source')}",
        f"- Baseline Measured: {summary.get('baseline', {}).get('measured')}",
        "",
        "## Summary",
        "",
        "| 평가 지표 | 목표 | 측정 결과 | 달성 여부 | 근거 |",
        "|---|---:|---:|---|---|",
    ]
    for label, key in rows:
        metric = summary.get("metrics", {}).get(key, {})
        lines.append(
            f"| {label} | {metric.get('targetDisplay', '-')} | {metric.get('resultDisplay', '-')} | {metric.get('status', '-')} | {metric.get('evidence', '-')} |"
        )

    lines.extend(["", "## Evaluated Agent Logs", ""])
    for item in details.get("logs", []):
        lines.append(
            f"- `{item.get('path')}` mode=`{item.get('mode')}` agentMode=`{item.get('agentMode')}` elapsed=`{item.get('elapsedSeconds')}`"
        )

    lines.extend(["", "## Artifact Completion", ""])
    lines.append("Summary metric uses `requirement-planning` logs with `agentMode=execute`. Other rows are shown for traceability.")
    lines.append("")
    lines.append("| Log | Project | Completion | Missing/Invalid |")
    lines.append("|---|---|---:|---|")
    for item in details.get("artifactCompletion", []):
        if not item.get("applicable"):
            lines.append(f"| `{item.get('logPath')}` | `{item.get('projectDir')}` | N/A | not an artifact generation run |")
            continue
        missing = [
            name
            for name, check in (item.get("checks") or {}).items()
            if not (check.get("exists") and check.get("valid"))
        ]
        lines.append(f"| `{item.get('logPath')}` | `{item.get('projectDir')}` | {item.get('completionPercent')}% | {', '.join(missing) or 'none'} |")

    lines.extend(["", "## Validation First Pass", ""])
    lines.append("| Log | make generate | make manifests | make test | e2e |")
    lines.append("|---|---|---|---|---|")
    for item in details.get("validationPass", []):
        results = item.get("results") or {}
        lines.append(
            f"| `{item.get('logPath')}` | {status(results, 'makeGenerate')} | {status(results, 'makeManifests')} | {status(results, 'makeTest')} | {status(results, 'e2e')} |"
        )

    lines.extend(["", "## Error Response", ""])
    if details.get("errorResponse"):
        lines.append("| Log | Failed Tool | Failed Step | Recovery Plan | Response Seconds |")
        lines.append("|---|---|---|---|---:|")
        for item in details["errorResponse"]:
            lines.append(
                f"| `{item.get('logPath')}` | {item.get('failedTool')} | {item.get('failedStep')} | {item.get('recoveryPlanStatus')} | {item.get('responseSeconds')} |"
            )
    else:
        lines.append("No failure/recovery logs were included.")

    return "\n".join(lines).rstrip() + "\n"


def write_report(path: str | Path, summary: dict[str, Any], details: dict[str, Any]) -> None:
    Path(path).write_text(render_report(summary, details), encoding="utf-8")


def status(results: dict[str, Any], key: str) -> str:
    value = results.get(key) or {}
    return str(value.get("firstAttempt") or "not-measured")
