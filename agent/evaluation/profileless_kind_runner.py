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
from agent.tools.controller_ir import (
    DeletionPolicy,
    ReconcileStrategy,
)
from agent.tools.controller_ir_builder import build_controller_ir


DEFAULT_REQUIREMENTS = [
    "requirements/web-service.txt",
    "requirements/secret-sync.txt",
    "requirements/scheduled-task.txt",
    "requirements/namespace-label-policy.txt",
]

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
        action="append",
        default=[],
        help="Run one requirement. Repeat to build a custom matrix.",
    )
    parser.add_argument(
        "--requirements",
        nargs="*",
        default=DEFAULT_REQUIREMENTS,
        help="Requirement matrix used when --requirement is omitted.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--cluster-name",
        default="profileless-matrix",
    )
    args = parser.parse_args()

    requirements = [
        resolve(value)
        for value in (args.requirement or args.requirements)
    ]
    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    work_root = Path(
        tempfile.mkdtemp(prefix="k8sagent-profileless-kind-")
    )
    try:
        results = [
            run_requirement(
                requirement,
                output_dir / "cases" / requirement.stem,
                work_root,
                args.cluster_name,
            )
            for requirement in requirements
        ]
        status = (
            "passed"
            if results and all(
                item.get("status") == "passed" for item in results
            )
            else "failed"
        )
        payload = {
            "createdAt": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "status": status,
            "profileUsed": False,
            "results": results,
        }
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


def run_requirement(
    requirement: Path,
    output_dir: Path,
    work_root: Path,
    cluster_name: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    compile_result = compile_requirement(
        requirement,
        output_dir / "compile",
        work_root,
    )
    if not compile_result.get("passed"):
        return result_payload(
            "failed",
            requirement,
            compile_result,
            {},
            [],
            "profile-less compile failed",
        )

    spec_path = Path(compile_result["specPath"])
    project_dir = Path(compile_result["projectDir"])
    contract = build_kind_contract(
        read_yaml(spec_path),
        project_dir,
        cluster_name,
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
    return payload


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
    setup_resources = []
    rbac_checks = [
        {
            "verb": "update",
            "resource": (
                f"{str(api.get('plural') or pluralize(api['kind'].lower()))}"
                "/status"
            ),
            "apiGroup": api["apiGroup"],
        }
    ]
    for resource in ir.renderable_resources():
        name = managed_name(resource, sample_name, sample_spec)
        resource_name = RESOURCE_NAMES[resource.kind]
        managed_resources.append(
            {
                "resource": resource_name,
                "name": name,
                "deletionPolicy": (
                    "retain"
                    if resource.deletion_policy == DeletionPolicy.RETAIN
                    else "garbage-collect"
                ),
            }
        )
        if resource.strategy == ReconcileStrategy.PATCH_EXISTING:
            setup_resources.append(
                {
                    "apiVersion": resource.api_version,
                    "kind": resource.kind,
                    "metadata": {"name": name},
                }
            )
        update = lifecycle_update(resource, sample_spec, name)
        if update and not update_spec:
            update_spec.update(update["spec"])
            update_assertions.extend(update["assertions"])
        rbac_checks.append(
            {
                "verb": (
                    "update"
                    if resource.strategy
                    == ReconcileStrategy.PATCH_EXISTING
                    else "create"
                ),
                "resource": pluralize(resource_name),
                "apiGroup": resource_api_group(resource_name),
            }
        )
    validator_config = {
        "resource": api["kind"].lower(),
        "sampleName": sample_name,
        "managedResources": managed_resources,
        "updateSpec": update_spec,
        "updateAssertions": update_assertions,
        "setupResources": setup_resources,
        "rbacChecks": rbac_checks,
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


def lifecycle_update(
    resource: Any,
    sample_spec: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    for mapping in resource.field_mappings:
        field = mapping.source_path.removeprefix("spec.")
        current = sample_spec.get(field)
        if mapping.target_path == "spec.replicas" and isinstance(
            current,
            int,
        ):
            updated = current + 1
            return update_contract(
                field,
                updated,
                resource,
                name,
                "spec.replicas",
            )
        if mapping.target_path == "spec.suspend" and isinstance(
            current,
            bool,
        ):
            return update_contract(
                field,
                not current,
                resource,
                name,
                "spec.suspend",
            )
        if (
            mapping.target_path == "metadata.labels"
            and isinstance(current, dict)
        ):
            updated = {**current, "profileless-e2e": "updated"}
            return update_contract(
                field,
                updated,
                resource,
                name,
                "metadata.labels.profileless-e2e",
                "updated",
            )
    return {}


def update_contract(
    field: str,
    updated: Any,
    resource: Any,
    name: str,
    path: str,
    expected: Any | None = None,
) -> dict[str, Any]:
    return {
        "spec": {field: updated},
        "assertions": [
            {
                "resource": RESOURCE_NAMES[resource.kind],
                "name": name,
                "path": path,
                "equals": updated if expected is None else expected,
            }
        ],
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
    output_dir.mkdir(parents=True, exist_ok=True)
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
