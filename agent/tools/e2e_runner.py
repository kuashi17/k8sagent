#!/usr/bin/env python3
"""Run or dry-run kind based e2e validation for a generated Operator."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run or execute kind based Operator e2e validation.")
    parser.add_argument("--input", help="Path to generated operator spec YAML.")
    parser.add_argument("--profile", help="Path to an Operator profile YAML. Existing fallback behavior is used when omitted.")
    parser.add_argument("--project", help="Path to generated Kubebuilder project.")
    parser.add_argument("--cluster-name", help="kind cluster name.")
    parser.add_argument("--sample", help="Sample Custom Resource YAML to apply.")
    parser.add_argument("--clean", action="store_true", help="Delete existing sample resources before applying the sample.")
    parser.add_argument("--delete-pvc", action="store_true", help="Delete the sample PVC during --clean. By default PVC is kept.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without executing. This is the default.")
    parser.add_argument("--execute", action="store_true", help="Actually run kind/kubectl/make commands.")
    args = parser.parse_args()

    if args.dry_run and args.execute:
        print("Use either --dry-run or --execute, not both.", file=sys.stderr)
        return 2

    spec = load_spec(Path(args.input)) if args.input else {}
    profile = load_profile(Path(args.profile)) if args.profile else {}
    project_dir = resolve_project(args.project, spec)
    cluster_name = resolve_cluster_name(args.cluster_name, spec, profile)
    sample_path = resolve_sample(args.sample, spec, profile, project_dir)
    validate_inputs(project_dir, sample_path)

    expected = load_sample_expectations(sample_path, profile)
    profile_config = build_profile_config(spec, profile, expected, args.profile)
    plan = build_plan(project_dir, cluster_name, sample_path, expected, profile_config, clean=args.clean, delete_pvc=args.delete_pvc)
    if not args.execute:
        print_dry_run(plan)
        return 0

    return execute_plan(plan)


def load_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"operator spec not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"operator spec must be a YAML mapping: {path}")
    return data


def load_profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"profile YAML not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"profile YAML must be a mapping: {path}")
    data["_profilePath"] = str(path)
    return data


def resolve_project(value: str | None, spec: dict[str, Any]) -> Path:
    if value:
        return Path(value)
    workspace = spec.get("project", {}).get("workspace")
    if workspace:
        return Path(workspace)
    raise SystemExit("--project is required when --input does not contain project.workspace")


def resolve_cluster_name(value: str | None, spec: dict[str, Any], profile: dict[str, Any]) -> str:
    if value:
        return value
    profile_cluster_name = profile.get("e2e", {}).get("clusterName")
    if profile_cluster_name:
        return profile_cluster_name
    cluster_name = spec.get("e2e", {}).get("clusterName")
    if cluster_name:
        return cluster_name
    raise SystemExit("--cluster-name is required when --input does not contain e2e.clusterName")


def resolve_sample(value: str | None, spec: dict[str, Any], profile: dict[str, Any], project_dir: Path) -> Path:
    if value:
        return Path(value)
    sample_path = profile.get("e2e", {}).get("samplePath") or spec.get("e2e", {}).get("sample", {}).get("path")
    if not sample_path:
        raise SystemExit("--sample is required when --input does not contain e2e.sample.path")
    path = Path(sample_path)
    return path if path.is_absolute() else project_dir / path


def validate_inputs(project_dir: Path, sample_path: Path) -> None:
    if not project_dir.is_dir():
        raise SystemExit(f"project directory not found: {project_dir}")
    if not (project_dir / "Makefile").is_file():
        raise SystemExit(f"Makefile not found under project directory: {project_dir}")
    if not sample_path.is_file():
        raise SystemExit(f"sample YAML not found: {sample_path}")


def load_sample_expectations(sample_path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    sample = yaml.safe_load(sample_path.read_text(encoding="utf-8"))
    if not isinstance(sample, dict):
        raise SystemExit(f"sample YAML must be a mapping: {sample_path}")
    profile_defaults = profile.get("sampleDefaults") or {}
    default_spec = profile_defaults.get("spec") or {}
    default_metadata = profile_defaults.get("metadata") or {}
    spec = {**default_spec, **(sample.get("spec") or {})}
    metadata = {**default_metadata, **(sample.get("metadata") or {})}
    return {
        "crName": metadata.get("name", "trainingjob-sample"),
        "image": spec.get("image", ""),
        "gpuCount": int(spec.get("gpuCount") or 0),
        "pvcName": spec.get("pvcName", ""),
        "datasetPath": spec.get("datasetPath", ""),
        "outputPath": spec.get("outputPath", ""),
    }


def build_profile_config(spec: dict[str, Any], profile: dict[str, Any], expected: dict[str, Any], profile_path: str | None) -> dict[str, Any]:
    api = spec.get("api") or {}
    e2e = profile.get("e2e") or {}
    custom_resource = e2e.get("customResource") or {}
    validation = profile.get("jobSpecValidation") or {}
    pvc = e2e.get("pvc") or {}
    env_names = e2e.get("envNames") or {}
    warning = profile.get("warnings", {}).get("gpuPending", {}) or {}

    crd_name = custom_resource.get("crdName") or infer_crd_name(api) or "trainingjobs.ml.ai.sample.io"
    cr_resource = custom_resource.get("resource") or api.get("kind", "TrainingJob").lower()
    job_template = validation.get("jobNameTemplate") or "{metadata.name}-job"
    pod_selector_template = validation.get("podSelectorTemplate") or "job-name={metadata.name}-job"
    job_name = render_template(job_template, expected)
    pod_selector = render_template(pod_selector_template, expected)
    gpu_resource_name = e2e.get("gpuResourceName") or "nvidia.com/gpu"
    mount_path = pvc.get("mountPath") or "/workspace"
    volume_name = pvc.get("volumeName") or "workspace"

    return {
        "profilePath": profile_path or "",
        "profileName": profile.get("profileName", "default-trainingjob-fallback"),
        "managedResources": profile.get("managedResources") or ["Job"],
        "referencedResources": profile.get("referencedResources") or ["Pod", "PersistentVolumeClaim"],
        "crdName": crd_name,
        "crResource": cr_resource,
        "jobNameTemplate": job_template,
        "jobName": job_name,
        "podSelectorTemplate": pod_selector_template,
        "podSelector": pod_selector,
        "pvcMountPath": mount_path,
        "pvcVolumeName": volume_name,
        "pvcStorage": pvc.get("storage") or first_setup_resource_value(profile, "PersistentVolumeClaim", "storage") or "1Gi",
        "gpuResourceName": gpu_resource_name,
        "envNames": {
            "datasetPath": env_names.get("datasetPath") or "DATASET_PATH",
            "outputPath": env_names.get("outputPath") or "OUTPUT_PATH",
        },
        "gpuPendingWarning": {
            "enabled": warning.get("enabled", True),
            "match": warning.get("match") or [f"Insufficient {gpu_resource_name}", gpu_resource_name],
            "message": warning.get("message") or "Pod is Pending due to insufficient GPU resources; treated as warning.",
        },
        "jobSpecValidationChecks": validation.get("checks") or [],
    }


def infer_crd_name(api: dict[str, Any]) -> str:
    kind = api.get("kind", "")
    group = api.get("group", "")
    domain = api.get("domain", "")
    if not kind or not group or not domain:
        return ""
    return f"{pluralize(kind.lower())}.{group}.{domain}"


def render_template(template: str, expected: dict[str, Any]) -> str:
    return template.replace("{metadata.name}", str(expected["crName"]))


def first_setup_resource_value(profile: dict[str, Any], kind: str, key: str) -> Any:
    for resource in profile.get("e2e", {}).get("setupResources") or []:
        if resource.get("kind") == kind and resource.get(key):
            return resource[key]
    return None


def pluralize(value: str) -> str:
    if value.endswith("s"):
        return value + "es"
    if value.endswith("y"):
        return value[:-1] + "ies"
    return value + "s"


def build_plan(
    project_dir: Path,
    cluster_name: str,
    sample_path: Path,
    expected: dict[str, Any],
    profile_config: dict[str, Any],
    clean: bool,
    delete_pvc: bool,
) -> dict[str, Any]:
    context = f"kind-{cluster_name}"
    cr_name = expected["crName"]
    job_name = profile_config["jobName"]
    pod_selector = profile_config["podSelector"]
    cr_resource = profile_config["crResource"]
    clean_steps = []
    if clean:
        clean_steps = [
            {"name": f"clean-delete-{cr_resource}", "command": ["kubectl", "--context", context, "delete", cr_resource, cr_name, "--ignore-not-found"], "cwd": "."},
            {"name": "clean-delete-job", "command": ["kubectl", "--context", context, "delete", "job", job_name, "--ignore-not-found"], "cwd": "."},
            {"name": "clean-delete-pods", "command": ["kubectl", "--context", context, "delete", "pod", "-l", pod_selector, "--ignore-not-found"], "cwd": "."},
            {"name": "clean-delete-pvc", "command": ["kubectl", "--context", context, "delete", "pvc", expected["pvcName"], "--ignore-not-found"], "cwd": ".", "enabled": delete_pvc},
            {"name": f"clean-confirm-{cr_resource}-deleted", "command": ["kubectl", "--context", context, "get", cr_resource, cr_name], "cwd": ".", "expectFailure": True, "retries": 10},
            {"name": "clean-confirm-job-deleted", "command": ["kubectl", "--context", context, "get", "job", job_name], "cwd": ".", "expectFailure": True, "retries": 10},
            {"name": "clean-confirm-pods-deleted", "command": ["kubectl", "--context", context, "get", "pods", "-l", pod_selector, "-o", "jsonpath={.items}"], "cwd": ".", "expectEmptyStdout": True, "retries": 10},
        ]
    return {
        "projectDir": str(project_dir),
        "clusterName": cluster_name,
        "context": context,
        "sample": str(sample_path),
        "clean": clean,
        "deletePvc": delete_pvc,
        "expected": expected,
        "profileConfig": profile_config,
        "crName": cr_name,
        "jobName": job_name,
        "steps": [
            {"name": "kind-get-clusters", "command": ["kind", "get", "clusters"], "cwd": "."},
            {"name": "kind-create-cluster-if-missing", "command": ["kind", "create", "cluster", "--name", cluster_name], "cwd": "."},
            {"name": "kubectl-cluster-info", "command": ["kubectl", "cluster-info", "--context", context], "cwd": "."},
            {"name": "kubectl-use-context", "command": ["kubectl", "config", "use-context", context], "cwd": "."},
            {"name": "make-install", "command": ["make", "install"], "cwd": str(project_dir)},
            {"name": "kubectl-get-crd", "command": ["kubectl", "--context", context, "get", "crd", profile_config["crdName"]], "cwd": "."},
            *clean_steps,
            {"name": "kubectl-apply-pvc", "command": ["kubectl", "--context", context, "apply", "-f", "<generated-pvc-yaml>"], "cwd": "."},
            {"name": "make-run-controller", "command": ["make", "run"], "cwd": str(project_dir), "background": True},
            {"name": "kubectl-apply-sample", "command": ["kubectl", "--context", context, "apply", "-f", str(sample_path)], "cwd": "."},
            {"name": f"kubectl-get-{cr_resource}", "command": ["kubectl", "--context", context, "get", cr_resource, cr_name, "-o", "yaml"], "cwd": ".", "retries": 10},
            {"name": "kubectl-get-job", "command": ["kubectl", "--context", context, "get", "job", job_name, "-o", "yaml"], "cwd": ".", "retries": 15},
            {"name": "kubectl-get-pods", "command": ["kubectl", "--context", context, "get", "pods", "-l", pod_selector, "-o", "yaml"], "cwd": ".", "retries": 10},
            {"name": f"kubectl-get-{cr_resource}-status", "command": ["kubectl", "--context", context, "get", cr_resource, cr_name, "-o", "jsonpath={.status}"], "cwd": ".", "retries": 10},
        ],
    }


def print_dry_run(plan: dict[str, Any]) -> None:
    print("Dry-run mode: no kind, kubectl, or make commands will be executed.")
    print(f"Project directory: {plan['projectDir']}")
    print(f"kind cluster name: {plan['clusterName']}")
    print(f"kube context: {plan['context']}")
    print(f"Sample YAML: {plan['sample']}")
    print(f"Clean before apply: {plan['clean']}")
    print(f"Delete sample PVC during clean: {plan['deletePvc']}")
    print(f"Profile: {plan['profileConfig']['profileName']} ({plan['profileConfig']['profilePath'] or 'fallback defaults'})")
    print()
    print("Profile-derived values:")
    print(f"- CRD name: {plan['profileConfig']['crdName']}")
    print(f"- Custom Resource kubectl resource: {plan['profileConfig']['crResource']}")
    print(f"- Managed resources: {', '.join(plan['profileConfig']['managedResources'])}")
    print(f"- Referenced resources: {', '.join(plan['profileConfig']['referencedResources'])}")
    print(f"- Job name template: {plan['profileConfig']['jobNameTemplate']} -> {plan['profileConfig']['jobName']}")
    print(f"- Pod selector template: {plan['profileConfig']['podSelectorTemplate']} -> {plan['profileConfig']['podSelector']}")
    print(f"- GPU resource name: {plan['profileConfig']['gpuResourceName']}")
    print(f"- PVC mount path: {plan['profileConfig']['pvcMountPath']}")
    print(f"- Dataset env name: {plan['profileConfig']['envNames']['datasetPath']}")
    print(f"- Output env name: {plan['profileConfig']['envNames']['outputPath']}")
    print(f"- GPU Pending warning keywords: {', '.join(plan['profileConfig']['gpuPendingWarning']['match'])}")
    print()
    print("Sample expectations:")
    for key in ("image", "gpuCount", "pvcName", "datasetPath", "outputPath"):
        print(f"- {key}: {plan['expected'][key]}")
    print()
    print("Job spec validation checks:")
    for check_item in validation_check_names(plan["profileConfig"]):
        print(f"- {check_item}")
    print()
    print("Pod Pending warning rule:")
    print(f"- If Pod is Pending and its condition message matches {plan['profileConfig']['gpuPendingWarning']['match']}, record warning instead of failing.")
    print()
    print("Summary additions:")
    print("- jobSpecValidation")
    print("- warnings")
    print("- clean/deletePvc")
    print()
    print("Planned e2e steps:")
    for index, step in enumerate(plan["steps"], start=1):
        print(f"{index}. [{step['name']}]")
        if step.get("enabled") is False:
            print("   status: disabled")
        print(f"   cwd: {step['cwd']}")
        print(f"   command: {' '.join(step['command'])}")
        if step.get("background"):
            print("   mode: background process")


def validation_check_names(profile_config: dict[str, Any]) -> list[str]:
    checks = profile_config.get("jobSpecValidationChecks") or []
    if checks:
        return [str(item.get("name", "unnamed check")) for item in checks]
    return [
        "container image matches spec.image",
        f"{profile_config['gpuResourceName']} limit matches spec.gpuCount, or is absent when gpuCount is 0",
        "PVC volume claimName matches spec.pvcName",
        f"{profile_config['pvcMountPath']} volumeMount exists",
        f"{profile_config['envNames']['datasetPath']} env matches spec.datasetPath",
        f"{profile_config['envNames']['outputPath']} env matches spec.outputPath",
    ]


def execute_plan(plan: dict[str, Any]) -> int:
    log_dir = Path("logs") / "e2e" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {
        "projectDir": plan["projectDir"],
        "clusterName": plan["clusterName"],
        "context": plan["context"],
        "sample": plan["sample"],
        "clean": plan["clean"],
        "deletePvc": plan["deletePvc"],
        "expected": plan["expected"],
        "execute": True,
        "logDir": str(log_dir),
        "steps": [],
        "warnings": [],
        "jobSpecValidation": None,
        "profileConfig": plan["profileConfig"],
        "failedStep": None,
    }

    env = os.environ.copy()
    env["PATH"] = f"{Path.cwd() / '.tools/bin'}:{env.get('PATH', '')}"
    controller_process: subprocess.Popen[str] | None = None

    try:
        clusters = run_step(1, plan["steps"][0], log_dir, env)
        summary["steps"].append(clusters)
        write_summary(log_dir, summary)
        if clusters["status"] != "succeeded":
            return fail(summary, clusters, log_dir)

        if plan["clusterName"] not in Path(clusters["stdoutLog"]).read_text(encoding="utf-8").splitlines():
            create = run_step(2, plan["steps"][1], log_dir, env)
            summary["steps"].append(create)
            write_summary(log_dir, summary)
            if create["status"] != "succeeded":
                return fail(summary, create, log_dir)
        else:
            skipped = skipped_step(2, plan["steps"][1], log_dir, "cluster already exists")
            summary["steps"].append(skipped)
            write_summary(log_dir, summary)

        write_pvc_yaml(log_dir, plan)
        executable_steps = plan["steps"][2:]
        for offset, step in enumerate(executable_steps, start=3):
            if step.get("enabled") is False:
                skipped = skipped_step(offset, step, log_dir, "step disabled")
                summary["steps"].append(skipped)
                write_summary(log_dir, summary)
                continue
            if step["name"] == "kubectl-apply-pvc":
                step = {**step, "command": ["kubectl", "--context", plan["context"], "apply", "-f", str(log_dir / "sample-pvc.yaml")]}
            if step.get("background"):
                controller_process = start_background_step(offset, step, log_dir, env)
                summary["steps"].append(
                    {
                        "name": step["name"],
                        "command": step["command"],
                        "cwd": step["cwd"],
                        "status": "running",
                        "exitCode": None,
                        "stdoutLog": str(log_dir / f"{offset:02d}-{step['name']}.stdout.log"),
                        "stderrLog": str(log_dir / f"{offset:02d}-{step['name']}.stderr.log"),
                    }
                )
                write_summary(log_dir, summary)
                time.sleep(3)
                continue

            result = run_step_with_retry(offset, step, log_dir, env)
            summary["steps"].append(result)
            write_summary(log_dir, summary)
            if result["status"] != "succeeded":
                return fail(summary, result, log_dir)

        validation = validate_job_spec(Path(step_log(summary, "kubectl-get-job", "stdoutLog")), plan["expected"], plan["profileConfig"])
        summary["jobSpecValidation"] = validation
        if not validation["passed"]:
            failure = {"name": "job-spec-validation", "exitCode": 1}
            return fail(summary, failure, log_dir)

        pod_warning = detect_gpu_pending_warning(Path(step_log(summary, "kubectl-get-pods", "stdoutLog")), plan["profileConfig"])
        if pod_warning:
            summary["warnings"].append(pod_warning)
            write_summary(log_dir, summary)

        print(f"e2e validation completed. Logs: {log_dir}")
        return 0
    finally:
        if controller_process is not None and controller_process.poll() is None:
            controller_process.send_signal(signal.SIGINT)
            try:
                controller_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                controller_process.kill()


def run_step(index: int, step: dict[str, Any], log_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    stdout_log = log_dir / f"{index:02d}-{step['name']}.stdout.log"
    stderr_log = log_dir / f"{index:02d}-{step['name']}.stderr.log"
    print(f"+ ({step['cwd']}) {' '.join(step['command'])}")
    completed = subprocess.run(step["command"], cwd=Path(step["cwd"]), env=env, text=True, capture_output=True)
    stdout_log.write_text(completed.stdout, encoding="utf-8")
    stderr_log.write_text(completed.stderr, encoding="utf-8")
    status = "succeeded" if completed.returncode == 0 else "failed"
    if step.get("expectFailure"):
        status = "succeeded" if completed.returncode != 0 else "failed"
    if step.get("expectEmptyStdout"):
        status = "succeeded" if completed.stdout.strip() in ("", "[]") else "failed"
    return {
        "name": step["name"],
        "command": step["command"],
        "cwd": step["cwd"],
        "exitCode": completed.returncode,
        "status": status,
        "stdoutLog": str(stdout_log),
        "stderrLog": str(stderr_log),
    }


def run_step_with_retry(index: int, step: dict[str, Any], log_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    retries = int(step.get("retries", 1))
    result = run_step(index, step, log_dir, env)
    attempt = 1
    while result["status"] != "succeeded" and attempt < retries:
        time.sleep(2)
        attempt += 1
        result = run_step(index, step, log_dir, env)
    result["attempts"] = attempt
    return result


def start_background_step(index: int, step: dict[str, Any], log_dir: Path, env: dict[str, str]) -> subprocess.Popen[str]:
    stdout_log = open(log_dir / f"{index:02d}-{step['name']}.stdout.log", "w", encoding="utf-8")
    stderr_log = open(log_dir / f"{index:02d}-{step['name']}.stderr.log", "w", encoding="utf-8")
    print(f"+ ({step['cwd']}) {' '.join(step['command'])} [background]")
    return subprocess.Popen(step["command"], cwd=Path(step["cwd"]), env=env, text=True, stdout=stdout_log, stderr=stderr_log)


def skipped_step(index: int, step: dict[str, Any], log_dir: Path, message: str) -> dict[str, Any]:
    stdout_log = log_dir / f"{index:02d}-{step['name']}.stdout.log"
    stderr_log = log_dir / f"{index:02d}-{step['name']}.stderr.log"
    stdout_log.write_text(message, encoding="utf-8")
    stderr_log.write_text("", encoding="utf-8")
    return {
        "name": step["name"],
        "command": step["command"],
        "cwd": step["cwd"],
        "exitCode": 0,
        "status": "skipped",
        "stdoutLog": str(stdout_log),
        "stderrLog": str(stderr_log),
    }


def write_pvc_yaml(log_dir: Path, plan: dict[str, Any]) -> None:
    expected = plan["expected"]
    profile_config = plan["profileConfig"]
    (log_dir / "sample-pvc.yaml").write_text(
        f"""apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: {expected["pvcName"]}
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: {profile_config["pvcStorage"]}
""",
        encoding="utf-8",
    )


def validate_job_spec(job_yaml: Path, expected: dict[str, Any], profile_config: dict[str, Any]) -> dict[str, Any]:
    job = yaml.safe_load(job_yaml.read_text(encoding="utf-8"))
    pod_spec = job.get("spec", {}).get("template", {}).get("spec", {})
    containers = pod_spec.get("containers") or []
    container = containers[0] if containers else {}
    env = {item.get("name"): item.get("value") for item in container.get("env", [])}
    mounts = container.get("volumeMounts") or []
    volumes = pod_spec.get("volumes") or []
    limits = container.get("resources", {}).get("limits", {}) or {}
    gpu_resource_name = profile_config["gpuResourceName"]
    mount_path = profile_config["pvcMountPath"]
    volume_name = profile_config["pvcVolumeName"]
    dataset_env_name = profile_config["envNames"]["datasetPath"]
    output_env_name = profile_config["envNames"]["outputPath"]

    checks = [
        check("container image", expected["image"], container.get("image")),
        check("gpu limit", str(expected["gpuCount"]), normalize_gpu_limit(limits.get(gpu_resource_name), expected["gpuCount"])),
        check("pvc claimName", expected["pvcName"], first_pvc_claim(volumes)),
        check(f"{mount_path} volumeMount", volume_name, mount_name_for_path(mounts, mount_path)),
        check(f"{dataset_env_name} env", expected["datasetPath"], env.get(dataset_env_name)),
        check(f"{output_env_name} env", expected["outputPath"], env.get(output_env_name)),
    ]
    return {"passed": all(item["status"] == "passed" for item in checks), "checks": checks}


def check(name: str, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "name": name,
        "expected": expected,
        "actual": actual,
        "status": "passed" if expected == actual else "failed",
    }


def normalize_gpu_limit(value: Any, expected_gpu_count: int) -> str:
    if expected_gpu_count == 0 and value is None:
        return "0"
    return str(value)


def first_pvc_claim(volumes: list[dict[str, Any]]) -> str:
    for volume in volumes:
        claim = volume.get("persistentVolumeClaim", {}).get("claimName")
        if claim:
            return claim
    return ""


def mount_name_for_path(mounts: list[dict[str, Any]], mount_path: str) -> str:
    for mount in mounts:
        if mount.get("mountPath") == mount_path:
            return mount.get("name", "")
    return ""


def detect_gpu_pending_warning(pods_yaml: Path, profile_config: dict[str, Any]) -> str:
    warning = profile_config["gpuPendingWarning"]
    if not warning.get("enabled", True):
        return ""
    keywords = [str(item) for item in warning.get("match") or []]
    pods = yaml.safe_load(pods_yaml.read_text(encoding="utf-8"))
    for pod in pods.get("items", []):
        if pod.get("status", {}).get("phase") != "Pending":
            continue
        conditions = pod.get("status", {}).get("conditions", [])
        text = " ".join(str(condition.get("message", "")) for condition in conditions)
        if any(keyword in text for keyword in keywords):
            return str(warning["message"])
    return ""


def step_log(summary: dict[str, Any], name: str, key: str) -> str:
    for step in reversed(summary["steps"]):
        if step["name"] == name:
            return step[key]
    raise KeyError(f"step not found in summary: {name}")


def fail(summary: dict[str, Any], result: dict[str, Any], log_dir: Path) -> int:
    summary["failedStep"] = result["name"]
    write_summary(log_dir, summary)
    print(f"e2e validation failed at step: {result['name']} (exit code {result['exitCode']})", file=sys.stderr)
    print(f"Logs: {log_dir}", file=sys.stderr)
    return result["exitCode"] or 1


def write_summary(log_dir: Path, summary: dict[str, Any]) -> None:
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
