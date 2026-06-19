"""Profile-specific validators for the generic kind deployment engine."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Protocol

import yaml


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

	configMap := &corev1.ConfigMap{ObjectMeta: metav1.ObjectMeta{Name: configMapName, Namespace: appConfig.Namespace}}
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
		if statusErr := r.updateStatus(ctx, &appConfig, "Error", configMapName, err.Error()); statusErr != nil {
			return ctrl.Result{}, statusErr
		}
		return ctrl.Result{}, err
	}
	return ctrl.Result{}, r.updateStatus(ctx, &appConfig, "Ready", configMapName, "ConfigMap is ready.")
}

func (r *AppConfigReconciler) updateStatus(ctx context.Context, appConfig *appv1alpha1.AppConfig, phase, configMapName, message string) error {
	if appConfig.Status.Phase == phase && appConfig.Status.ConfigMapName == configMapName && appConfig.Status.Message == message {
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

func (r *AppConfigReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).For(&appv1alpha1.AppConfig{}).Owns(&corev1.ConfigMap{}).Complete(r)
}
'''


class DeploymentEngine(Protocol):
    project: Path
    sample: Path
    log_dir: Path
    timeout_seconds: int
    checks: dict[str, Any]
    failed_step: str

    def run_cmd(
        self,
        name: str,
        command: list[str],
        cwd: Path | None = None,
        timeout: int = 180,
        check: bool = True,
    ) -> dict[str, Any]: ...


class DeploymentValidator(Protocol):
    name: str

    def planned_steps(self, include_prepare: bool, include_lifecycle: bool) -> list[dict[str, Any]]: ...
    def prepare(self, engine: DeploymentEngine) -> None: ...
    def verify_initial(self, engine: DeploymentEngine) -> None: ...
    def verify_lifecycle(self, engine: DeploymentEngine) -> None: ...
    def summary(self) -> dict[str, Any]: ...


class AppConfigConfigMapValidator:
    name = "appconfig-configmap"

    def __init__(self, config: dict[str, Any]) -> None:
        self.resource = str(config.get("resource") or "appconfig")
        self.sample_name = str(config.get("sampleName") or "appconfig-sample")
        self.configmap_name = str(config.get("configMapName") or "appconfig-sample-config")
        self.controller_path = str(config.get("controllerPath") or "internal/controller/appconfig_controller.go")
        self.namespace = str(config.get("namespace") or "")

    def planned_steps(self, include_prepare: bool, include_lifecycle: bool) -> list[dict[str, Any]]:
        steps = []
        if include_prepare:
            steps.append({"name": "prepare-appconfig-controller", "mutating": True, "validator": self.name})
        steps.append({"name": "verify-appconfig-configmap-and-status", "validator": self.name})
        if include_lifecycle:
            steps.extend(
                {"name": name, "mutating": True, "validator": self.name}
                for name in ("verify-update", "verify-disabled", "verify-delete", "restore-sample")
            )
        return steps

    def prepare(self, engine: DeploymentEngine) -> None:
        engine.failed_step = "prepare-controller"
        controller = engine.project / self.controller_path
        if not controller.is_file():
            raise RuntimeError(f"AppConfig controller file not found: {controller}")
        current = controller.read_text(encoding="utf-8")
        if "ConfigMap is ready." in current and "appconfigs/status" in current:
            engine.checks["controllerPrepared"] = {"changed": False, "path": relative(controller)}
            return
        controller.write_text(APPCONFIG_CONTROLLER, encoding="utf-8")
        engine.checks["controllerPrepared"] = {"changed": True, "path": relative(controller)}

    def verify_initial(self, engine: DeploymentEngine) -> None:
        engine.failed_step = "apply-sample"
        engine.run_cmd(
            "kubectl-apply-sample",
            self.kubectl(["apply", "-f", str(engine.sample)]),
            timeout=120,
        )
        result = engine.run_cmd(
            "kubectl-get-custom-resource",
            self.kubectl(["get", self.resource, self.sample_name, "-o", "json"]),
            timeout=60,
        )
        engine.checks["customResource"] = parse_json(result["stdout"])
        data = self.wait_configmap_data(engine, expected_config_data(engine.sample), "initial")
        status = self.wait_phase(engine, "Ready", self.configmap_name, "initial")
        engine.checks["managedResource"] = {
            "kind": "ConfigMap",
            "name": self.configmap_name,
            "dataMatches": True,
            "data": data,
        }
        engine.checks["customResourceStatus"] = status

    def verify_lifecycle(self, engine: DeploymentEngine) -> None:
        self.verify_update(engine)
        self.verify_disabled(engine)
        self.verify_delete_and_restore(engine)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "customResource": {
                "resource": self.resource,
                "name": self.sample_name,
                "namespace": self.namespace,
            },
            "managedResource": {"kind": "ConfigMap", "name": self.configmap_name},
        }

    def verify_update(self, engine: DeploymentEngine) -> None:
        engine.failed_step = "verify-update"
        updated = load_yaml(engine.sample)
        updated.setdefault("spec", {}).setdefault("configData", {})
        updated["spec"]["configData"].update(
            {"LOG_LEVEL": "debug", "FEATURE_FLAG": "false", "UPDATED_BY": "kind-deployment-runner"}
        )
        updated_sample = write_temp_sample(engine, "update", updated)
        expected = expected_config_data(updated_sample)
        engine.run_cmd(
            "kubectl-apply-updated-sample",
            self.kubectl(["apply", "-f", str(updated_sample)]),
            timeout=120,
        )
        data = self.wait_configmap_data(engine, expected, "updated")
        status = self.wait_phase(engine, "Ready", self.configmap_name, "updated")
        engine.checks["lifecycleUpdate"] = {"dataMatches": data == expected, "expectedData": expected, "actualData": data, "status": status}

    def verify_disabled(self, engine: DeploymentEngine) -> None:
        engine.failed_step = "verify-disabled"
        disabled = load_yaml(engine.sample)
        disabled.setdefault("spec", {})["enabled"] = False
        disabled_sample = write_temp_sample(engine, "disabled", disabled)
        engine.run_cmd(
            "kubectl-apply-disabled-sample",
            self.kubectl(["apply", "-f", str(disabled_sample)]),
            timeout=120,
        )
        status = self.wait_phase(engine, "Disabled", "", "disabled")
        engine.checks["lifecycleDisabled"] = {
            "phase": status.get("phase"),
            "managedResourceAbsent": self.wait_absent(engine, "configmap", self.configmap_name, "configmap"),
        }

    def verify_delete_and_restore(self, engine: DeploymentEngine) -> None:
        engine.failed_step = "verify-delete"
        engine.run_cmd(
            "kubectl-delete-custom-resource",
            self.kubectl(
                ["delete", self.resource, self.sample_name, "--ignore-not-found"]
            ),
            timeout=120,
        )
        engine.checks["lifecycleDelete"] = {
            "customResourceAbsent": self.wait_absent(engine, self.resource, self.sample_name, "custom-resource"),
            "managedResourceAbsent": self.wait_absent(engine, "configmap", self.configmap_name, "configmap"),
        }
        engine.failed_step = "restore-sample"
        engine.run_cmd(
            "kubectl-restore-sample",
            self.kubectl(["apply", "-f", str(engine.sample)]),
            timeout=120,
        )
        expected = expected_config_data(engine.sample)
        restored_data = self.wait_configmap_data(engine, expected, "restored")
        restored_status = self.wait_phase(engine, "Ready", self.configmap_name, "restored")
        engine.checks["lifecycleRestore"] = {"dataMatches": restored_data == expected, "status": restored_status}

    def wait_configmap_data(self, engine: DeploymentEngine, expected: dict[str, str], label: str) -> dict[str, str]:
        engine.failed_step = f"wait-configmap-{label}"
        deadline = time.time() + engine.timeout_seconds
        last: dict[str, str] = {}
        while time.time() < deadline:
            result = engine.run_cmd(
                f"kubectl-get-configmap-{label}",
                self.kubectl(
                    ["get", "configmap", self.configmap_name, "-o", "json"]
                ),
                check=False,
            )
            if result["exitCode"] == 0:
                data = {str(key): str(value) for key, value in (parse_json(result["stdout"]).get("data") or {}).items()}
                last = data
                if data == expected:
                    return data
            time.sleep(3)
        raise RuntimeError(f"ConfigMap data did not match for {label}: expected={expected}, actual={last}")

    def wait_phase(self, engine: DeploymentEngine, phase: str, configmap_name: str, label: str) -> dict[str, Any]:
        engine.failed_step = f"wait-status-{label}"
        deadline = time.time() + engine.timeout_seconds
        last: dict[str, Any] = {}
        while time.time() < deadline:
            result = engine.run_cmd(
                f"kubectl-get-custom-resource-status-{label}",
                self.kubectl(
                    ["get", self.resource, self.sample_name, "-o", "json"]
                ),
                check=False,
            )
            if result["exitCode"] == 0:
                status = parse_json(result["stdout"]).get("status") or {}
                last = status
                if status.get("phase") == phase and status.get("configMapName", "") == configmap_name:
                    return status
            time.sleep(3)
        raise RuntimeError(f"AppConfig phase did not become {phase}: {last}")

    def wait_absent(self, engine: DeploymentEngine, resource: str, name: str, label: str) -> bool:
        deadline = time.time() + engine.timeout_seconds
        while time.time() < deadline:
            result = engine.run_cmd(
                f"kubectl-get-{label}-absent",
                self.kubectl(["get", resource, name, "-o", "json"]),
                check=False,
            )
            if result["exitCode"] != 0 and is_not_found(result):
                result["status"] = "succeeded"
                result["expectedNotFound"] = True
                return True
            time.sleep(3)
        return False

    def kubectl(self, arguments: list[str]) -> list[str]:
        command = ["kubectl"]
        if self.namespace:
            command.extend(["--namespace", self.namespace])
        command.extend(arguments)
        return command


def create_validator(name: str, config: dict[str, Any]) -> DeploymentValidator:
    if name == AppConfigConfigMapValidator.name:
        return AppConfigConfigMapValidator(config)
    raise ValueError(f"Unsupported kind deployment validator: {name}")


def expected_config_data(sample: Path) -> dict[str, str]:
    spec = load_yaml(sample).get("spec") or {}
    return {str(key): str(value) for key, value in (spec.get("configData") or {}).items()}


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_temp_sample(engine: DeploymentEngine, suffix: str, data: dict[str, Any]) -> Path:
    temp = engine.log_dir / f"{engine.sample.stem}-{suffix}.yaml"
    temp.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return temp


def parse_json(text: str) -> dict[str, Any]:
    import json

    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def is_not_found(result: dict[str, Any]) -> bool:
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    return "NotFound" in text or "not found" in text


def relative(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)
