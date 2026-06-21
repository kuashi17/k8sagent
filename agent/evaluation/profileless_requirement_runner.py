#!/usr/bin/env python3
"""Run profile-less Agent dry-runs against generic Operator requirements."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.controller_quality import evaluate_controller_quality


DEFAULT_REQUIREMENTS = [
    "requirements/redis-cache.txt",
    "requirements/secret-sync.txt",
    "requirements/scheduled-task.txt",
    "requirements/web-service.txt",
    "requirements/pvc-provisioner.txt",
    "requirements/namespace-label-policy.txt",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate that the Agent can handle requirements without a profile.")
    parser.add_argument("--requirements", nargs="*", default=DEFAULT_REQUIREMENTS)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--run-level", default="fast", choices=["fast", "standard"])
    parser.add_argument(
        "--mode",
        default="dry-run",
        choices=["dry-run", "execute"],
        help="execute also requires generated artifacts to pass the quality matrix.",
    )
    args = parser.parse_args()

    out_dir = Path(args.output_dir) if args.output_dir else Path("evaluation/results/profileless") / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [
        run_requirement(path, args.run_level, args.mode)
        for path in args.requirements
    ]
    summary = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "runLevel": args.run_level,
        "mode": args.mode,
        "profileHintsDisabled": True,
        "status": "passed" if all(item["passed"] for item in results) else "failed",
        "requirements": results,
    }
    (out_dir / "profileless-results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "profileless-report.md").write_text(render_report(summary), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "outputDir": str(out_dir)}, indent=2, ensure_ascii=False))
    return 0 if summary["status"] == "passed" else 1


def run_requirement(
    requirement: str,
    run_level: str,
    mode: str,
) -> dict[str, Any]:
    started = time.time()
    command = [
        "python3",
        "agent/langchain_agent.py",
        "--requirement",
        requirement,
        "--mode",
        mode,
        "--run-level",
        run_level,
        "--disable-profile-hints",
    ]
    if mode == "execute":
        command.append("--execute")
    result = subprocess.run(command, text=True, capture_output=True, timeout=420)
    log_dir = extract_agent_log_dir(result.stdout)
    summary = read_json(Path(log_dir) / "summary.json") if log_dir else {}
    selected_profile = summary.get("selectedProfile") or {}
    errors = summary.get("errors") or []
    project_dir = Path(
        summary.get("targetProjectDir")
        or infer_project_dir(
            (summary.get("requirementSummary") or {}).get("kind", "")
        )
    )
    spec_path = Path(
        (summary.get("generatedFiles") or {}).get("operatorSpec") or ""
    )
    quality = evaluate_controller_quality(
        project_dir,
        spec_path,
        summary.get("toolResults") or [],
    )
    passed = (
        result.returncode == 0
        and not errors
        and selected_profile.get("selectionMode") == "disabled"
        and not selected_profile.get("path")
        and summary.get("requirementSummary", {}).get("kind")
        and summary.get("validatedToolCalls")
        and not summary.get("rejectedToolCalls")
        and (mode == "dry-run" or quality["status"] == "passed")
    )
    return {
        "requirement": requirement,
        "exitCode": result.returncode,
        "elapsedSeconds": round(time.time() - started, 3),
        "logDir": log_dir,
        "kind": (summary.get("requirementSummary") or {}).get("kind", ""),
        "managedResources": (summary.get("requirementSummary") or {}).get("managedResources", []),
        "profileSelectionMode": selected_profile.get("selectionMode", ""),
        "profileHint": selected_profile.get("path", ""),
        "validatedTools": [item.get("tool") for item in summary.get("validatedToolCalls") or []],
        "rejectedCount": len(summary.get("rejectedToolCalls") or []),
        "errors": errors,
        "controllerQuality": quality,
        "passed": bool(passed),
    }


def infer_project_dir(kind: str) -> str:
    slug = re.sub(r"(?<!^)(?=[A-Z])", "-", kind).lower()
    return f"workspace/generated-operators/{slug}-operator"


def extract_agent_log_dir(stdout: str) -> str:
    for line in stdout.splitlines():
        if line.startswith("Agent logs:"):
            return line.split(":", 1)[1].strip()
    return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Profile-less Requirement Test Report",
        "",
        f"- Status: `{summary['status']}`",
        f"- Run level: `{summary['runLevel']}`",
        f"- Mode: `{summary['mode']}`",
        f"- Created at: `{summary['createdAt']}`",
        "",
        "| Requirement | Kind | Managed Resources | Profile Mode | Controller Score | Result |",
        "|---|---|---|---|---|---|",
    ]
    for item in summary["requirements"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{item['requirement']}`",
                    f"`{item.get('kind') or 'unknown'}`",
                    f"`{', '.join(item.get('managedResources') or []) or 'unknown'}`",
                    f"`{item.get('profileSelectionMode') or 'unknown'}`",
                    f"`{(item.get('controllerQuality') or {}).get('score', 0)}`",
                    "`passed`" if item.get("passed") else "`failed`",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            (
                "Profile mode `disabled` means profile discovery and "
                "selection were both disabled; planning used only the "
                "requirement and retrieved knowledge."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
