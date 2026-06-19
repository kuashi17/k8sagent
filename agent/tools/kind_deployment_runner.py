#!/usr/bin/env python3
"""CLI entry point and generic deployment engine for profile-backed kind runs."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.tools.kind_deployment_validators import create_validator  # noqa: E402


DEFAULT_PROJECT = REPO_ROOT / "workspace" / "generated-operators" / "app-config-operator"
DEFAULT_CLUSTER = "appconfig-deploy"
DEFAULT_IMAGE = "app-config-operator:kind"
DEFAULT_NAMESPACE = "app-config-operator-system"
DEFAULT_DEPLOYMENT = "app-config-operator-controller-manager"
DEFAULT_VALIDATOR = "appconfig-configmap"


class KindDeploymentEngine:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project = resolve_path(args.project)
        self.sample = resolve_path(args.sample) if args.sample else self.project / "config" / "samples" / "app_v1alpha1_appconfig.yaml"
        self.timeout_seconds = parse_duration_seconds(args.timeout)
        validator_config = json.loads(args.validator_config) if args.validator_config else {}
        validator_config.setdefault("namespace", args.namespace)
        if args.sample_name:
            validator_config.setdefault("sampleName", args.sample_name)
        if args.configmap_name:
            validator_config.setdefault("configMapName", args.configmap_name)
        self.validator = create_validator(args.validator, validator_config)
        self.log_dir = REPO_ROOT / "logs" / "kind-deployment" / datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict[str, Any]] = []
        self.checks: dict[str, Any] = {}
        self.failed_step = ""
        self.started = time.time()

    def run(self) -> int:
        try:
            self.preflight()
            if self.args.dry_run:
                self.checks["dryRun"] = {
                    "plannedSteps": self.planned_steps(),
                    "message": "Dry-run only. No files, images, clusters, or Kubernetes resources were changed.",
                }
                summary = self.write_summary("succeeded")
                print(json.dumps(summary, indent=2, ensure_ascii=False))
                return 0
            if not self.args.skip_prepare_controller:
                self.validator.prepare(self)
            if not self.args.skip_prevalidation:
                self.run_cmd("make-generate", ["make", "generate"], cwd=self.project)
                self.run_cmd("make-manifests", ["make", "manifests"], cwd=self.project)
                self.run_cmd("make-test", ["make", "test"], cwd=self.project)
            self.ensure_cluster()
            self.run_cmd("docker-build", ["make", "docker-build", f"IMG={self.args.image}"], cwd=self.project, timeout=600)
            self.run_cmd("kind-load-image", ["kind", "load", "docker-image", self.args.image, "--name", self.args.cluster_name], timeout=300)
            self.run_cmd("make-install", ["make", "install"], cwd=self.project, timeout=300)
            self.run_cmd("make-deploy", ["make", "deploy", f"IMG={self.args.image}"], cwd=self.project, timeout=300)
            self.wait_deployment()
            self.verify_rbac()
            self.validator.verify_initial(self)
            if not self.args.skip_lifecycle:
                self.validator.verify_lifecycle(self)
            status = "succeeded"
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            self.failed_step = self.failed_step or "unknown"
            self.checks["error"] = str(exc)
            print(f"FAILED at {self.failed_step}: {exc}", file=sys.stderr)
        summary = self.write_summary(status)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if status == "succeeded" else 1

    def planned_steps(self) -> list[dict[str, Any]]:
        validator_steps = self.validator.planned_steps(
            include_prepare=not self.args.skip_prepare_controller,
            include_lifecycle=not self.args.skip_lifecycle,
        )
        steps = []
        if not self.args.skip_prepare_controller and validator_steps:
            steps.append(validator_steps.pop(0))
        if not self.args.skip_prevalidation:
            steps.extend(
                [
                    {"name": "make-generate", "command": ["make", "generate"], "cwd": rel(self.project)},
                    {"name": "make-manifests", "command": ["make", "manifests"], "cwd": rel(self.project)},
                    {"name": "make-test", "command": ["make", "test"], "cwd": rel(self.project)},
                ]
            )
        steps.extend(
            [
            {"name": "ensure-kind-cluster", "clusterName": self.args.cluster_name, "mutating": True},
            {"name": "docker-build", "command": ["make", "docker-build", f"IMG={self.args.image}"], "mutating": True},
            {"name": "kind-load-image", "command": ["kind", "load", "docker-image", self.args.image, "--name", self.args.cluster_name], "mutating": True},
            {"name": "make-install", "command": ["make", "install"], "mutating": True},
            {"name": "make-deploy", "command": ["make", "deploy", f"IMG={self.args.image}"], "mutating": True},
            {"name": "verify-controller-deployment"},
            ]
        )
        steps.extend(validator_steps)
        return steps

    def preflight(self) -> None:
        self.failed_step = "preflight"
        if not self.project.is_dir():
            raise RuntimeError(f"project directory not found: {self.project}")
        if not self.sample.is_file():
            raise RuntimeError(f"sample file not found: {self.sample}")
        for binary in ["docker", "kind", "kubectl", "make", "go"]:
            if not shutil.which(binary):
                raise RuntimeError(f"required binary not found in PATH: {binary}")
        self.run_cmd("docker-info", ["docker", "info"], timeout=30)

    def ensure_cluster(self) -> None:
        self.failed_step = "ensure-cluster"
        result = self.run_cmd("kind-get-clusters", ["kind", "get", "clusters"], check=False)
        clusters = set(result["stdout"].split())
        if self.args.cluster_name in clusters:
            self.checks["cluster"] = {"name": self.args.cluster_name, "created": False}
            self.run_cmd("kubectl-context", ["kubectl", "cluster-info", "--context", f"kind-{self.args.cluster_name}"], timeout=60)
            self.activate_context()
            return
        self.run_cmd("kind-create-cluster", ["kind", "create", "cluster", "--name", self.args.cluster_name], timeout=600)
        self.checks["cluster"] = {"name": self.args.cluster_name, "created": True}
        self.activate_context()

    def activate_context(self) -> None:
        context = f"kind-{self.args.cluster_name}"
        self.run_cmd(
            "kubectl-use-context",
            ["kubectl", "config", "use-context", context],
            timeout=30,
        )
        self.checks["kubectlContext"] = context

    def wait_deployment(self) -> None:
        self.failed_step = "wait-deployment"
        self.run_cmd(
            "kubectl-rollout-status",
            [
                "kubectl",
                "rollout",
                "status",
                f"deployment/{self.args.deployment}",
                "-n",
                self.args.namespace,
                "--timeout",
                self.args.timeout,
            ],
            timeout=parse_duration_seconds(self.args.timeout) + 30,
        )
        result = self.run_cmd(
            "kubectl-get-deployment",
            ["kubectl", "get", "deployment", self.args.deployment, "-n", self.args.namespace, "-o", "json"],
        )
        deployment = json.loads(result["stdout"])
        self.checks["controllerDeployment"] = {
            "namespace": self.args.namespace,
            "name": self.args.deployment,
            "availableReplicas": deployment.get("status", {}).get("availableReplicas", 0),
            "readyReplicas": deployment.get("status", {}).get("readyReplicas", 0),
        }

    def verify_rbac(self) -> None:
        checks = []
        service_account = (
            f"system:serviceaccount:{self.args.namespace}:"
            f"{self.args.deployment.removesuffix('-controller-manager')}-controller-manager"
        )
        for index, item in enumerate(self.validator.rbac_checks(), start=1):
            resource_name, _, subresource = item["resource"].partition("/")
            resource = resource_name
            if item.get("apiGroup"):
                resource = f"{resource}.{item['apiGroup']}"
            command = [
                "kubectl",
                "auth",
                "can-i",
                item["verb"],
                resource,
                "--namespace",
                self.args.namespace,
                "--as",
                service_account,
            ]
            if subresource:
                command.extend(["--subresource", subresource])
            result = self.run_cmd(
                f"kubectl-auth-can-i-{index}",
                command,
                check=False,
            )
            allowed = result["exitCode"] == 0 and result["stdout"].strip() == "yes"
            checks.append({**item, "allowed": allowed})
            if not allowed:
                self.failed_step = "rbac-preflight"
                raise RuntimeError(
                    f"Controller RBAC denied: {item['verb']} {resource}"
                )
        self.checks["rbacPreflight"] = checks

    def run_cmd(
        self,
        name: str,
        command: list[str],
        cwd: Path | None = None,
        timeout: int = 180,
        check: bool = True,
    ) -> dict[str, Any]:
        if self.args.dry_run:
            result = {
                "name": name,
                "command": command,
                "cwd": str(cwd or REPO_ROOT),
                "stdout": "",
                "stderr": "",
                "exitCode": 0,
                "status": "dry-run",
                "elapsedSeconds": 0,
            }
            self.steps.append(result)
            return result
        started = time.time()
        completed = subprocess.run(command, cwd=cwd or REPO_ROOT, text=True, capture_output=True, timeout=timeout)
        elapsed = round(time.time() - started, 3)
        result = {
            "name": name,
            "command": command,
            "cwd": str(cwd or REPO_ROOT),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "exitCode": completed.returncode,
            "status": "succeeded" if completed.returncode == 0 else "failed",
            "elapsedSeconds": elapsed,
        }
        self.steps.append(result)
        safe_name = f"{len(self.steps):02d}-{name}"
        (self.log_dir / f"{safe_name}.stdout.log").write_text(completed.stdout, encoding="utf-8")
        (self.log_dir / f"{safe_name}.stderr.log").write_text(completed.stderr, encoding="utf-8")
        if check and completed.returncode != 0:
            self.failed_step = name
            raise RuntimeError(f"command failed exitCode={completed.returncode}: {' '.join(command)}")
        return result

    def write_summary(self, status: str) -> dict[str, Any]:
        summary = {
            "status": status,
            "failedStep": self.failed_step if status != "succeeded" else "",
            "engine": "kind-deployment",
            "validator": self.validator.summary(),
            "project": rel(self.project),
            "clusterName": self.args.cluster_name,
            "image": self.args.image,
            "namespace": self.args.namespace,
            "deployment": self.args.deployment,
            "sample": rel(self.sample),
            "checks": self.checks,
            "steps": self.steps,
            "elapsedSeconds": round(time.time() - self.started, 3),
            "logDir": rel(self.log_dir),
        }
        (self.log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary


def parse_duration_seconds(value: str) -> int:
    if value.endswith("s"):
        return int(value[:-1])
    if value.endswith("m"):
        return int(value[:-1]) * 60
    return int(value)


def resolve_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else REPO_ROOT / value


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the generic kind deployment engine with a profile-specific validator.")
    parser.add_argument("--project", default=str(DEFAULT_PROJECT))
    parser.add_argument("--cluster-name", default=DEFAULT_CLUSTER)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--sample", default="")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--deployment", default=DEFAULT_DEPLOYMENT)
    parser.add_argument("--validator", default=DEFAULT_VALIDATOR)
    parser.add_argument("--validator-config", default="", help="Validator-specific JSON configuration.")
    parser.add_argument("--sample-name", default="", help="Deprecated AppConfig validator compatibility option.")
    parser.add_argument("--configmap-name", default="", help="Deprecated AppConfig validator compatibility option.")
    parser.add_argument("--timeout", default="180s")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-lifecycle", action="store_true", help="Skip update, disabled, delete, and restore lifecycle checks.")
    parser.add_argument("--skip-prepare-controller", action="store_true", help="Use the existing controller source without fixture-specific preparation.")
    parser.add_argument("--skip-prevalidation", action="store_true", help="Skip make generate/manifests/test because the caller already validated the project.")
    args = parser.parse_args()
    return KindDeploymentEngine(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
