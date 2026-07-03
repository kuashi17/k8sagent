#!/usr/bin/env python3
"""Run uncached Local LLM planning repeatedly and compare semantic outputs."""

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
DEFAULT_MATRIX = REPO_ROOT / "evaluation" / "fixtures" / "local-llm-consistency-matrix.yaml"


def extract_log_dir(stdout: str) -> str:
    for line in reversed(stdout.splitlines()):
        if line.startswith("Agent logs:"):
            return line.split(":", 1)[1].strip()
    return ""


def semantic_record(summary: dict[str, Any]) -> dict[str, Any]:
    requirement = summary.get("requirementSummary") or {}
    final = ((summary.get("finalLLM") or {}).get("output") or {})
    clarification = summary.get("clarificationContext") or {}
    return {
        "kind": requirement.get("kind") or "",
        "api": {
            key: requirement.get(key) or ""
            for key in ("domain", "group", "version")
        },
        "managedResources": requirement.get("managedResources") or [],
        "observedResources": requirement.get("observedResources") or [],
        "missingInformation": summary.get("missingInformation") or [],
        "validatedTools": [
            item.get("tool") for item in summary.get("validatedToolCalls") or []
        ],
        "rejectedTools": [
            item.get("tool") for item in summary.get("rejectedToolCalls") or []
        ],
        "decision": final.get("executionDecision") or "",
        "errorCode": clarification.get("errorCode") or "",
        "llmPlannerUsed": bool(summary.get("llmPlannerUsed")),
    }


def expected_failures(record: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    failures = []
    for key, value in expected.items():
        if record.get(key) != value:
            failures.append({"field": key, "expected": value, "actual": record.get(key)})
    return failures


def run_case(case: dict[str, Any], runs: int, output_dir: Path) -> dict[str, Any]:
    records = []
    executions = []
    case_root = output_dir / str(case["id"])
    for index in range(1, runs + 1):
        run_root = case_root / f"run-{index}"
        command = [
            sys.executable,
            "agent/langchain_agent.py",
            "--requirement",
            str(case["requirement"]),
            "--disable-profile-hints",
            "--mode",
            "dry-run",
            "--run-level",
            "fast",
            "--no-cache",
            "--artifact-dir",
            str(run_root / "artifacts"),
            "--workspace",
            str(run_root / "workspace"),
        ]
        started = time.monotonic()
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=int(case.get("timeoutSeconds") or 180),
        )
        log_dir = extract_log_dir(completed.stdout)
        summary_path = REPO_ROOT / log_dir / "summary.json" if log_dir else Path()
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if log_dir and summary_path.is_file()
            else {}
        )
        records.append(semantic_record(summary))
        executions.append(
            {
                "run": index,
                "exitCode": completed.returncode,
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "logDir": log_dir,
                "llmError": summary.get("llmError") or "",
            }
        )
    failures = expected_failures(records[0], case.get("expected") or {})
    consistent = len({json.dumps(item, sort_keys=True, ensure_ascii=False) for item in records}) == 1
    exits_ok = all(item["exitCode"] == 0 for item in executions)
    return {
        "id": case["id"],
        "status": "passed" if exits_ok and consistent and not failures else "failed",
        "consistent": consistent,
        "accuracyPassed": not failures,
        "failures": failures,
        "record": records[0],
        "executions": executions,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output-dir", default="evaluation/results/local-llm-consistency")
    args = parser.parse_args()
    matrix = yaml.safe_load(Path(args.matrix).read_text(encoding="utf-8")) or {}
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results = [run_case(case, args.runs, output_dir) for case in matrix.get("cases") or []]
    report = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cacheDisabled": True,
        "runsPerCase": args.runs,
        "status": "passed" if results and all(item["status"] == "passed" for item in results) else "failed",
        "results": results,
    }
    (output_dir / "local-llm-consistency.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({"status": report["status"], "cases": len(results), "runsPerCase": args.runs}, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
