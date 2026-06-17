#!/usr/bin/env python3
"""Deploy and verify the AppConfig Operator inside a kind cluster."""

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

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT = REPO_ROOT / "workspace" / "generated-operators" / "app-config-operator"
DEFAULT_CLUSTER = "appconfig-deploy"
DEFAULT_IMAGE = "app-config-operator:kind"
DEFAULT_NAMESPACE = "app-config-operator-system"
DEFAULT_DEPLOYMENT = "app-config-operator-controller-manager"
DEFAULT_SAMPLE_NAME = "appconfig-sample"
DEFAULT_CONFIGMAP_NAME = "appconfig-sample-config"


APPCONFIG_CONTROLLER = r'''/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"
	"reflect"

	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	"sigs.k8s.io/controller-runtime/pkg/log"

	appv1alpha1 "beginner.sample.io/app-config-operator/api/v1alpha1"
)

// AppConfigReconciler reconciles a AppConfig object
type AppConfigReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=app.beginner.sample.io,resources=appconfigs,verbs=get;list;watch;update;patch
// +kubebuilder:rbac:groups=app.beginner.sample.io,resources=appconfigs/status,verbs=get;update;patch
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete

func (r *AppConfigReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	logger := log.FromContext(ctx)

	var appConfig appv1alpha1.AppConfig
	if err := r.Get(ctx, req.NamespacedName, &appConfig); err != nil {
		if apierrors.IsNotFound(err) {
			return ctrl.Result{}, nil
		}
		return ctrl.Result{}, err
	}

	configMapName := appConfig.Name + "-config"
	if !appConfig.Spec.Enabled {
		var existing corev1.ConfigMap
		err := r.Get(ctx, client.ObjectKey{Namespace: appConfig.Namespace, Name: configMapName}, &existing)
		if err == nil {
			if deleteErr := r.Delete(ctx, &existing); deleteErr != nil && !apierrors.IsNotFound(deleteErr) {
				return ctrl.Result{}, deleteErr
			}
		} else if !apierrors.IsNotFound(err) {
			return ctrl.Result{}, err
		}
		return ctrl.Result{}, r.updateStatus(ctx, &appConfig, "Disabled", "", "AppConfig is disabled; ConfigMap is not created.")
	}

	configMap := &corev1.ConfigMap{
		ObjectMeta: metav1.ObjectMeta{
			Name:      configMapName,
			Namespace: appConfig.Namespace,
		},
	}
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, configMap, func() error {
		if configMap.Labels == nil {
			configMap.Labels = map[string]string{}
		}
		configMap.Labels["app.kubernetes.io/managed-by"] = "app-config-operator"
		configMap.Labels["app.beginner.sample.io/appconfig"] = appConfig.Name
		configMap.Data = copyStringMap(appConfig.Spec.ConfigData)
		return controllerutil.SetControllerReference(&appConfig, configMap, r.Scheme)
	})
	if err != nil {
		logger.Error(err, "failed to reconcile ConfigMap")
		statusErr := r.updateStatus(ctx, &appConfig, "Error", configMapName, err.Error())
		if statusErr != nil {
			return ctrl.Result{}, statusErr
		}
		return ctrl.Result{}, err
	}

	return ctrl.Result{}, r.updateStatus(ctx, &appConfig, "Ready", configMapName, "ConfigMap is ready.")
}

func (r *AppConfigReconciler) updateStatus(ctx context.Context, appConfig *appv1alpha1.AppConfig, phase, configMapName, message string) error {
	if appConfig.Status.Phase == phase &&
		appConfig.Status.ConfigMapName == configMapName &&
		appConfig.Status.Message == message {
		return nil
	}
	appConfig.Status.Phase = phase
	appConfig.Status.ConfigMapName = configMapName
	appConfig.Status.Message = message
	return r.Status().Update(ctx, appConfig)
}

func copyStringMap(input map[string]string) map[string]string {
	if input == nil {
		return map[string]string{}
	}
	output := make(map[string]string, len(input))
	for key, value := range input {
		output[key] = value
	}
	if reflect.DeepEqual(output, map[string]string{}) {
		return map[string]string{}
	}
	return output
}

// SetupWithManager sets up the controller with the Manager.
func (r *AppConfigReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&appv1alpha1.AppConfig{}).
		Owns(&corev1.ConfigMap{}).
		Complete(r)
}
'''


class Runner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.project = resolve_path(args.project)
        self.sample = resolve_path(args.sample) if args.sample else self.project / "config" / "samples" / "app_v1alpha1_appconfig.yaml"
        self.log_dir = REPO_ROOT / "logs" / "kind-deployment" / datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict[str, Any]] = []
        self.checks: dict[str, Any] = {}
        self.failed_step = ""
        self.started = time.time()

    def run(self) -> int:
        try:
            self.preflight()
            self.prepare_controller()
            self.run_cmd("make-generate", ["make", "generate"], cwd=self.project)
            self.run_cmd("make-manifests", ["make", "manifests"], cwd=self.project)
            self.run_cmd("make-test", ["make", "test"], cwd=self.project)
            self.ensure_cluster()
            self.run_cmd("docker-build", ["make", "docker-build", f"IMG={self.args.image}"], cwd=self.project, timeout=600)
            self.run_cmd("kind-load-image", ["kind", "load", "docker-image", self.args.image, "--name", self.args.cluster_name], timeout=300)
            self.run_cmd("make-install", ["make", "install"], cwd=self.project, timeout=300)
            self.run_cmd("make-deploy", ["make", "deploy", f"IMG={self.args.image}"], cwd=self.project, timeout=300)
            if self.args.dry_run:
                self.checks["dryRun"] = {"plannedSteps": len(self.steps), "message": "No cluster or workload verification was executed."}
                status = "succeeded"
                summary = self.write_summary(status)
                print(json.dumps(summary, indent=2, ensure_ascii=False))
                return 0
            self.wait_deployment()
            self.apply_sample()
            self.wait_configmap()
            self.wait_status()
            status = "succeeded"
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            self.failed_step = self.failed_step or "unknown"
            self.checks["error"] = str(exc)
            print(f"FAILED at {self.failed_step}: {exc}", file=sys.stderr)
        summary = self.write_summary(status)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if status == "succeeded" else 1

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

    def prepare_controller(self) -> None:
        self.failed_step = "prepare-controller"
        controller = self.project / "internal" / "controller" / "appconfig_controller.go"
        if not controller.is_file():
            raise RuntimeError(f"AppConfig controller file not found: {controller}")
        current = controller.read_text(encoding="utf-8")
        if "ConfigMap is ready." in current and "appconfigs/status" in current:
            self.checks["controllerPrepared"] = {"changed": False, "path": rel(controller)}
            return
        if self.args.dry_run:
            self.checks["controllerPrepared"] = {"changed": False, "wouldChange": True, "path": rel(controller)}
            return
        controller.write_text(APPCONFIG_CONTROLLER, encoding="utf-8")
        self.checks["controllerPrepared"] = {"changed": True, "path": rel(controller)}

    def ensure_cluster(self) -> None:
        self.failed_step = "ensure-cluster"
        result = self.run_cmd("kind-get-clusters", ["kind", "get", "clusters"], check=False)
        clusters = set(result["stdout"].split())
        if self.args.cluster_name in clusters:
            self.checks["cluster"] = {"name": self.args.cluster_name, "created": False}
            self.run_cmd("kubectl-context", ["kubectl", "cluster-info", "--context", f"kind-{self.args.cluster_name}"], timeout=60)
            return
        self.run_cmd("kind-create-cluster", ["kind", "create", "cluster", "--name", self.args.cluster_name], timeout=600)
        self.checks["cluster"] = {"name": self.args.cluster_name, "created": True}

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

    def apply_sample(self) -> None:
        self.failed_step = "apply-sample"
        self.run_cmd("kubectl-apply-sample", ["kubectl", "apply", "-f", str(self.sample)], timeout=120)
        result = self.run_cmd("kubectl-get-appconfig", ["kubectl", "get", "appconfig", self.args.sample_name, "-o", "json"], timeout=60)
        self.checks["appConfig"] = json.loads(result["stdout"])

    def wait_configmap(self) -> None:
        self.failed_step = "wait-configmap"
        deadline = time.time() + parse_duration_seconds(self.args.timeout)
        last = ""
        while time.time() < deadline:
            result = self.run_cmd(
                "kubectl-get-configmap",
                ["kubectl", "get", "configmap", self.args.configmap_name, "-o", "json"],
                check=False,
            )
            if result["exitCode"] == 0:
                configmap = json.loads(result["stdout"])
                data = configmap.get("data") or {}
                expected = expected_config_data(self.sample)
                if data == expected:
                    self.checks["configMap"] = {
                        "name": self.args.configmap_name,
                        "dataMatches": True,
                        "data": data,
                    }
                    return
                last = f"ConfigMap data mismatch: expected={expected}, actual={data}"
            else:
                last = result["stderr"] or result["stdout"]
            time.sleep(3)
        raise RuntimeError(f"ConfigMap was not ready: {last}")

    def wait_status(self) -> None:
        self.failed_step = "wait-status"
        deadline = time.time() + parse_duration_seconds(self.args.timeout)
        last: dict[str, Any] = {}
        while time.time() < deadline:
            result = self.run_cmd("kubectl-get-appconfig-status", ["kubectl", "get", "appconfig", self.args.sample_name, "-o", "json"], check=False)
            if result["exitCode"] == 0:
                appconfig = json.loads(result["stdout"])
                status = appconfig.get("status") or {}
                last = status
                if status.get("phase") == "Ready" and status.get("configMapName") == self.args.configmap_name:
                    self.checks["appConfigStatus"] = status
                    return
            time.sleep(3)
        raise RuntimeError(f"AppConfig status was not updated: {last}")

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
            "project": rel(self.project),
            "clusterName": self.args.cluster_name,
            "image": self.args.image,
            "namespace": self.args.namespace,
            "deployment": self.args.deployment,
            "sample": rel(self.sample),
            "sampleName": self.args.sample_name,
            "configMapName": self.args.configmap_name,
            "checks": self.checks,
            "steps": self.steps,
            "elapsedSeconds": round(time.time() - self.started, 3),
            "logDir": rel(self.log_dir),
        }
        (self.log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary


def expected_config_data(sample: Path) -> dict[str, str]:
    data = yaml.safe_load(sample.read_text(encoding="utf-8"))
    spec = data.get("spec") or {}
    return {str(key): str(value) for key, value in (spec.get("configData") or {}).items()}


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
    parser = argparse.ArgumentParser(description="Deploy AppConfig Operator into kind and verify Deployment, ConfigMap, and status.")
    parser.add_argument("--project", default=str(DEFAULT_PROJECT))
    parser.add_argument("--cluster-name", default=DEFAULT_CLUSTER)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--sample", default="")
    parser.add_argument("--namespace", default=DEFAULT_NAMESPACE)
    parser.add_argument("--deployment", default=DEFAULT_DEPLOYMENT)
    parser.add_argument("--sample-name", default=DEFAULT_SAMPLE_NAME)
    parser.add_argument("--configmap-name", default=DEFAULT_CONFIGMAP_NAME)
    parser.add_argument("--timeout", default="180s")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return Runner(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
