#!/usr/bin/env python3
"""Generate a profile-less Operator and validate it in kind."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.profile_kind_matrix import parse_summary
from agent.evaluation.profileless_compile_runner import (
    compile_requirement,
)
from agent.tools.artifact_patcher import normalize_spec
from agent.tools.controller_ir import DeletionPolicy
from agent.tools.controller_ir_builder import build_controller_ir


RESOURCE_NAMES = {
    "ConfigMap": "configmap",
    "Secret": "secret",
    "PersistentVolumeClaim": "persistentvolumeclaim",
    "CronJob": "cronjob",
    "Deployment": "deployment",
    "StatefulSet": "statefulset",
    "Service": "service",
    "Namespace": "namespace",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirement",
        default="requirements/web-service.txt",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--cluster-name",
        default="profileless-webservice",
    )
    args = parser.parse_args()

    requirement = resolve(args.requirement)
    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_root = Path(
        tempfile.mkdtemp(prefix="k8sagent-profileless-kind-")
    )
    try:
        compile_dir = output_dir / "compile"
        compile_result = compile_requirement(
            requirement,
            compile_dir,
            work_root,
        )
        if not compile_result.get("passed"):
            payload = result_payload(
                "failed",
                requirement,
                compile_result,
                {},
                [],
                "profile-less compile failed",
            )
            write_result(output_dir, payload)
            return 1

        spec_path = Path(compile_result["specPath"])
        project_dir = Path(compile_result["projectDir"])
        spec = read_yaml(spec_path)
        contract = build_kind_contract(
            spec,
            project_dir,
            args.cluster_name,
        )
        command = build_kind_command(contract)
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
        )
        deployment = parse_summary(completed.stdout)
        status = (
            "passed"
            if completed.returncode == 0
            and deployment.get("status") == "succeeded"
            else "failed"
        )
        payload = result_payload(
            status,
            requirement,
            compile_result,
            deployment,
            command,
            completed.stderr[-4000:],
        )
        write_result(output_dir, payload)
        print(
            json.dumps(
                {
                    "status": status,
                    "outputDir": relative(output_dir),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0 if status == "passed" else 1
    finally:
        shutil.rmtree(work_root, ignore_errors=True)


def build_kind_contract(
    spec: dict[str, Any],
    project_dir: Path,
    cluster_name: str,
) -> dict[str, Any]:
    model = normalize_spec(spec, {}, None)
    ir = build_controller_ir(model)
    project_name = str((model.get("project") or {}).get("name") or "")
    api = model["api"]
    sample_path = (
        project_dir
        / "config"
        / "samples"
        / f"{api['group']}_{api['version']}_{api['kind'].lower()}.yaml"
    )
    sample = read_yaml(sample_path)
    sample_name = str((sample.get("metadata") or {}).get("name") or "")
    sample_spec = sample.get("spec") or {}
    managed_resources = []
    update_spec: dict[str, Any] = {}
    update_assertions = []
    for resource in ir.renderable_resources():
        name = managed_name(resource, sample_name, sample_spec)
        managed_resources.append(
            {
                "resource": RESOURCE_NAMES[resource.kind],
                "name": name,
                "deletionPolicy": (
                    "retain"
                    if resource.deletion_policy == DeletionPolicy.RETAIN
                    else "garbage-collect"
                ),
            }
        )
        for mapping in resource.field_mappings:
            field = mapping.source_path.removeprefix("spec.")
            if (
                mapping.target_path == "spec.replicas"
                and field in sample_spec
                and not update_spec
            ):
                updated = int(sample_spec[field]) + 1
                update_spec[field] = updated
                update_assertions.append(
                    {
                        "resource": RESOURCE_NAMES[resource.kind],
                        "name": name,
                        "path": "spec.replicas",
                        "equals": updated,
                    }
                )
    plural = str(api.get("plural") or pluralize(api["kind"].lower()))
    validator_config = {
        "resource": api["kind"].lower(),
        "sampleName": sample_name,
        "managedResources": managed_resources,
        "updateSpec": update_spec,
        "updateAssertions": update_assertions,
        "rbacChecks": [
            {
                "verb": "update",
                "resource": f"{plural}/status",
                "apiGroup": api["apiGroup"],
            },
            *[
                {
                    "verb": "create",
                    "resource": pluralize(item["resource"]),
                    "apiGroup": resource_api_group(item["resource"]),
                }
                for item in managed_resources
                if item["deletionPolicy"] != "retain"
            ],
        ],
    }
    return {
        "project": str(project_dir),
        "clusterName": cluster_name,
        "image": f"{project_name}:profileless-kind",
        "sample": str(sample_path),
        "namespace": f"{project_name}-system",
        "deployment": f"{project_name}-controller-manager",
        "validatorConfig": validator_config,
    }


def build_kind_command(contract: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        "agent/tools/kind_deployment_runner.py",
        "--project",
        contract["project"],
        "--cluster-name",
        contract["clusterName"],
        "--image",
        contract["image"],
        "--sample",
        contract["sample"],
        "--namespace",
        contract["namespace"],
        "--deployment",
        contract["deployment"],
        "--validator",
        "managed-resources",
        "--validator-config",
        json.dumps(
            contract["validatorConfig"],
            ensure_ascii=False,
        ),
        "--skip-prepare-controller",
        "--skip-prevalidation",
    ]


def managed_name(
    resource: Any,
    sample_name: str,
    sample_spec: dict[str, Any],
) -> str:
    source = resource.name.source_path
    if source.startswith("spec."):
        value = sample_spec.get(source.removeprefix("spec."))
        if value:
            return str(value)
    suffix = resource.name.fallback_template.replace(
        "{metadata.name}-",
        "",
    )
    return f"{sample_name}-{suffix}"


def resource_api_group(resource: str) -> str:
    if resource in {"deployment", "statefulset", "daemonset"}:
        return "apps"
    if resource in {"cronjob", "job"}:
        return "batch"
    return ""


def pluralize(value: str) -> str:
    if value.endswith("s"):
        return value + "es"
    if value.endswith("y"):
        return value[:-1] + "ies"
    return value + "s"


def result_payload(
    status: str,
    requirement: Path,
    compile_result: dict[str, Any],
    deployment: dict[str, Any],
    command: list[str],
    error: str,
) -> dict[str, Any]:
    return {
        "createdAt": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "status": status,
        "requirement": relative(requirement),
        "profileUsed": False,
        "compile": compile_result,
        "kindCommand": command,
        "deploymentSummary": deployment,
        "error": error,
    }


def write_result(output_dir: Path, payload: dict[str, Any]) -> None:
    (output_dir / "profileless-kind-results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


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
