#!/usr/bin/env python3
"""Run enabled profile-backed kind validators as an integration matrix."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles",
        default="profiles/trainingjob.yaml,profiles/rediscache.yaml",
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for value in args.profiles.split(","):
        path = resolve(value.strip())
        profile = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        capability = profile.get("kindDeployment") or {}
        if not capability.get("enabled"):
            results.append(
                {
                    "profile": relative(path),
                    "status": "skipped",
                    "reason": "kindDeployment is not enabled",
                }
            )
            continue
        missing = missing_fixture_reason(capability)
        if missing:
            results.append(
                {
                    "profile": relative(path),
                    "status": "skipped",
                    "reason": missing,
                }
            )
            continue
        command = build_command(capability)
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )
        deployment_summary = parse_summary(completed.stdout)
        result = {
            "profile": relative(path),
            "status": "passed" if completed.returncode == 0 else "failed",
            "exitCode": completed.returncode,
            "command": command,
            "stdoutTail": completed.stdout[-4000:],
            "stderrTail": completed.stderr[-4000:],
            "deploymentSummary": deployment_summary,
        }
        results.append(result)
        print(
            json.dumps(
                {
                    "profile": result["profile"],
                    "status": result["status"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    summary = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": (
            "passed"
            if all(item["status"] in {"passed", "skipped"} for item in results)
            else "failed"
        ),
        "results": results,
    }
    (output_dir / "profile-kind-matrix.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0 if summary["status"] == "passed" else 1


def build_command(capability: dict[str, Any]) -> list[str]:
    command = [
        sys.executable,
        "agent/tools/kind_deployment_runner.py",
        "--project",
        str(capability["project"]),
        "--cluster-name",
        str(capability["clusterName"]),
        "--image",
        str(capability["image"]),
        "--sample",
        str(capability["sample"]),
        "--namespace",
        str(capability["namespace"]),
        "--deployment",
        str(capability["deployment"]),
        "--validator",
        str(capability["validator"]),
        "--validator-config",
        json.dumps(
            capability.get("validatorConfig") or {},
            ensure_ascii=False,
        ),
    ]
    if capability.get("skipPrepareController"):
        command.append("--skip-prepare-controller")
    if capability.get("skipPrevalidation"):
        command.append("--skip-prevalidation")
    return command


def missing_fixture_reason(capability: dict[str, Any]) -> str:
    project = resolve(str(capability.get("project") or ""))
    sample = resolve(str(capability.get("sample") or ""))
    missing = []
    if not project.is_dir():
        missing.append(f"project={relative(project)}")
    if not sample.is_file():
        missing.append(f"sample={relative(sample)}")
    if not missing:
        return ""
    return (
        "profile fixture is not available in this checkout; "
        "profileless kind matrix remains the portable full E2E gate: "
        + ", ".join(missing)
    )


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def parse_summary(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    objects = []
    for index, character in enumerate(stdout):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    summaries = [
        item
        for item in objects
        if "status" in item and "checks" in item
    ]
    if summaries:
        return summaries[-1]
    return objects[0] if objects else {}


if __name__ == "__main__":
    raise SystemExit(main())
