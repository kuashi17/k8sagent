#!/usr/bin/env python3
"""Compile and evaluate profile-less Operators in isolated workspaces."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.controller_quality import evaluate_controller_quality
from agent.evaluation.profileless_requirement_runner import (
    DEFAULT_REQUIREMENTS,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirements",
        nargs="*",
        default=DEFAULT_REQUIREMENTS,
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--work-root",
        default="",
        help="Optional workspace root. Defaults to a temporary directory.",
    )
    parser.add_argument(
        "--keep-workspaces",
        action="store_true",
        help="Keep generated projects for local inspection.",
    )
    args = parser.parse_args()

    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temporary = not args.work_root
    work_root = (
        resolve(args.work_root)
        if args.work_root
        else Path(tempfile.mkdtemp(prefix="k8sagent-profileless-"))
    )
    work_root.mkdir(parents=True, exist_ok=True)
    try:
        results = [
            compile_requirement(
                resolve(value),
                output_dir,
                work_root,
            )
            for value in args.requirements
        ]
    finally:
        if temporary and not args.keep_workspaces:
            shutil.rmtree(work_root, ignore_errors=True)

    summary = {
        "createdAt": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "status": (
            "passed"
            if all(item["passed"] for item in results)
            else "failed"
        ),
        "requirements": results,
    }
    write_json(output_dir / "profileless-compile-results.json", summary)
    (output_dir / "profileless-compile-report.md").write_text(
        render_report(summary),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "outputDir": relative(output_dir),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if summary["status"] == "passed" else 1


def compile_requirement(
    requirement_path: Path,
    output_dir: Path,
    work_root: Path,
) -> dict[str, Any]:
    started = time.perf_counter()
    slug = requirement_path.stem
    case_dir = output_dir / "cases" / slug
    case_dir.mkdir(parents=True, exist_ok=True)
    spec_path = case_dir / "operator-spec.yaml"
    steps: list[dict[str, Any]] = []

    spec_step = run_step(
        "spec-generator",
        [
            sys.executable,
            "agent/tools/spec_generator.py",
            relative(requirement_path),
            "--output",
            str(spec_path),
        ],
    )
    steps.append(spec_step)
    if spec_step["exitCode"] != 0:
        return failed_case(requirement_path, steps, started)

    spec = read_yaml(spec_path)
    project_name = str((spec.get("project") or {}).get("name") or "")
    project_dir = work_root / slug / project_name
    workspace = project_dir.parent
    workspace.mkdir(parents=True, exist_ok=True)

    scaffold_step = run_step(
        "scaffold",
        [
            sys.executable,
            "agent/tools/scaffold_runner.py",
            "--input",
            str(spec_path),
            "--workspace",
            str(workspace),
            "--execute",
            "--force",
        ],
    )
    steps.append(scaffold_step)
    if scaffold_step["exitCode"] != 0:
        return failed_case(
            requirement_path,
            steps,
            started,
            project_dir,
            spec_path,
        )

    patch_step = run_step(
        "artifact-patch",
        [
            sys.executable,
            "agent/tools/artifact_patcher.py",
            "--input",
            str(spec_path),
            "--project",
            str(project_dir),
            "--execute",
        ],
    )
    steps.append(patch_step)
    if patch_step["exitCode"] != 0:
        return failed_case(
            requirement_path,
            steps,
            started,
            project_dir,
            spec_path,
        )

    validation_step = run_step(
        "validation",
        ["make", "generate", "manifests", "test"],
        cwd=project_dir,
    )
    steps.append(validation_step)
    tool_results = [
        {
            "tool": "validation",
            "steps": [
                {
                    "target": "test",
                    "exitCode": validation_step["exitCode"],
                }
            ],
        }
    ]
    quality = evaluate_controller_quality(
        project_dir,
        spec_path,
        tool_results,
    )
    passed = (
        all(item["exitCode"] == 0 for item in steps)
        and quality.get("status") == "passed"
    )
    return {
        "requirement": relative(requirement_path),
        "kind": str((spec.get("api") or {}).get("kind") or ""),
        "managedResources": (
            (spec.get("controller") or {}).get("managedResources") or []
        ),
        "projectDir": str(project_dir),
        "specPath": str(spec_path),
        "steps": steps,
        "controllerQuality": quality,
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "passed": passed,
    }


def run_step(
    name: str,
    command: list[str],
    cwd: Path = REPO_ROOT,
) -> dict[str, Any]:
    started = time.perf_counter()
    env = os.environ.copy()
    env["PATH"] = f"{REPO_ROOT / '.tools/bin'}:{env.get('PATH', '')}"
    env["GOCACHE"] = env.get("GOCACHE", "/tmp/k8sagent-go-build")
    flags = env.get("GOFLAGS", "").split()
    if "-buildvcs=false" not in flags:
        flags.append("-buildvcs=false")
    env["GOFLAGS"] = " ".join(flags)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "exitCode": completed.returncode,
        "status": (
            "succeeded" if completed.returncode == 0 else "failed"
        ),
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "stdoutTail": completed.stdout[-4000:],
        "stderrTail": completed.stderr[-4000:],
    }


def failed_case(
    requirement_path: Path,
    steps: list[dict[str, Any]],
    started: float,
    project_dir: Path | None = None,
    spec_path: Path | None = None,
) -> dict[str, Any]:
    return {
        "requirement": relative(requirement_path),
        "projectDir": str(project_dir or ""),
        "specPath": str(spec_path or ""),
        "steps": steps,
        "controllerQuality": {},
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "passed": False,
    }


def render_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Profile-less Compile Report",
        "",
        f"- Status: `{summary['status']}`",
        f"- Created at: `{summary['createdAt']}`",
        "",
        "| Requirement | Kind | Managed Resources | Quality | Result |",
        "|---|---|---|---:|---|",
    ]
    for item in summary["requirements"]:
        quality = item.get("controllerQuality") or {}
        resources = (
            ", ".join(item.get("managedResources") or [])
            or "unknown"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{item['requirement']}`",
                    f"`{item.get('kind') or 'unknown'}`",
                    f"`{resources}`",
                    str(quality.get("score") or 0),
                    "`passed`" if item.get("passed") else "`failed`",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
