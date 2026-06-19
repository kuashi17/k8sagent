#!/usr/bin/env python3
"""Run the repository's unit, reliability, and optional integration checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=["quick", "standard", "full"],
        default="quick",
        help="quick avoids LLM/Docker; standard adds one Agent run; full adds kind and profileless checks.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Result directory. Defaults to evaluation/results/regression/<timestamp>.",
    )
    args = parser.parse_args()

    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else Path("evaluation/results/regression") / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    if not output_dir.is_absolute():
        output_dir = REPO_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    generated_snapshot = snapshot_tree(REPO_ROOT / "generated")
    try:
        return run_suite(args.suite, output_dir)
    finally:
        restore_tree(REPO_ROOT / "generated", generated_snapshot)


def run_suite(suite: str, output_dir: Path) -> int:
    checks = [
        run_check(
            "agent-unit-tests",
            [sys.executable, "-m", "unittest", "discover", "-s", "agent", "-p", "test_*.py", "-q"],
        ),
        run_check(
            "llm-unit-tests",
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "agent/llm",
                "-p",
                "test_*.py",
                "-q",
            ],
        ),
        run_check(
            "tool-unit-tests",
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "agent/tools",
                "-p",
                "test_*.py",
                "-q",
            ],
        ),
        run_check(
            "evaluation-unit-tests",
            [
                sys.executable,
                "-m",
                "unittest",
                "discover",
                "-s",
                "agent/evaluation",
                "-p",
                "test_*.py",
                "-q",
            ],
        ),
        run_check(
            "web-unit-tests",
            [sys.executable, "-m", "unittest", "discover", "-s", "web", "-p", "test_*.py", "-q"],
        ),
        run_check(
            "rag-quality-gate",
            [
                sys.executable,
                "agent/evaluation/rag_quality_gate.py",
                "--output",
                str(output_dir / "rag-quality.json"),
            ],
        ),
    ]

    reliability_command = [
        sys.executable,
        "agent/evaluation/reliability_test_runner.py",
        "--level",
        "full" if suite == "full" else "fast",
        "--output-dir",
        str(output_dir / "reliability"),
    ]
    if suite == "quick":
        reliability_command.append("--skip-agent-consistency")
    if suite != "full":
        reliability_command.append("--skip-kind-idempotency")
    checks.append(run_check("reliability", reliability_command))

    if suite == "full":
        checks.append(
            run_check(
                "profile-kind-matrix",
                [
                    sys.executable,
                    "agent/evaluation/profile_kind_matrix.py",
                    "--output-dir",
                    str(output_dir / "profile-kind"),
                ],
            )
        )
        checks.append(
            run_check(
                "profileless-requirements",
                [
                    sys.executable,
                    "agent/evaluation/profileless_requirement_runner.py",
                    "--output-dir",
                    str(output_dir / "profileless"),
                    "--run-level",
                    "fast",
                ],
            )
        )

    summary = {
        "suite": suite,
        "status": "passed" if all(check["exitCode"] == 0 for check in checks) else "failed",
        "checks": checks,
    }
    (output_dir / "regression-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps({"status": summary["status"], "outputDir": relative(output_dir)}, indent=2))
    write_performance_trend(output_dir, summary)
    return 0 if summary["status"] == "passed" else 1


def run_check(name: str, command: list[str]) -> dict[str, object]:
    print(f"\n[{name}] {' '.join(command)}", flush=True)
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True)
    return {
        "name": name,
        "command": command,
        "exitCode": completed.returncode,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
    }


def write_performance_trend(
    output_dir: Path,
    summary: dict[str, object],
) -> None:
    current = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "suite": summary["suite"],
        "status": summary["status"],
        "checks": {
            item["name"]: item["elapsedSeconds"]
            for item in summary["checks"]
        },
        "totalSeconds": round(
            sum(float(item["elapsedSeconds"]) for item in summary["checks"]),
            3,
        ),
    }
    previous = find_previous_performance(output_dir)
    payload = {"current": current, "previous": previous}
    (output_dir / "performance-trend.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def find_previous_performance(output_dir: Path) -> dict[str, object]:
    root = output_dir.parent
    candidates = sorted(
        (
            path
            for path in root.glob("*/performance-trend.json")
            if path.parent != output_dir
        ),
        reverse=True,
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        return data.get("current") or {}
    return {}


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def snapshot_tree(root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def restore_tree(root: Path, snapshot: dict[Path, bytes]) -> None:
    current_files = [path for path in root.rglob("*") if path.is_file()]
    for path in current_files:
        relative_path = path.relative_to(root)
        if relative_path not in snapshot:
            path.unlink()
    for relative_path, content in snapshot.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.is_file() or path.read_bytes() != content:
            path.write_bytes(content)
    for path in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        try:
            path.rmdir()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
