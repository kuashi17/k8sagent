"""Profile-specific validators for the generic kind deployment engine."""

from __future__ import annotations

import json
import base64
import re
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
    def rbac_checks(self) -> list[dict[str, str]]: ...


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

    def rbac_checks(self) -> list[dict[str, str]]:
        return [
            {
                "verb": "update",
                "resource": "appconfigs/status",
                "apiGroup": "app.beginner.sample.io",
            },
            {"verb": "create", "resource": "configmaps", "apiGroup": ""},
            {"verb": "delete", "resource": "configmaps", "apiGroup": ""},
        ]

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


class ManagedResourceValidator:
    """Declarative create/delete/restore validation for profile resources."""

    name = "managed-resources"

    def __init__(self, config: dict[str, Any]) -> None:
        self.resource = str(config.get("resource") or "")
        self.sample_name = str(config.get("sampleName") or "")
        self.namespace = str(config.get("namespace") or "")
        self.managed_resources = [
            {
                "resource": str(item.get("resource") or ""),
                "name": str(item.get("name") or self.sample_name),
                "deletionPolicy": str(
                    item.get("deletionPolicy") or "garbage-collect"
                ),
                "updatePolicy": str(
                    item.get("updatePolicy") or "in-place"
                ),
            }
            for item in config.get("managedResources") or []
            if isinstance(item, dict) and item.get("resource")
        ]
        self.status_phases = [
            str(item)
            for item in config.get("acceptedStatusPhases") or []
            if item
        ]
        self.setup_resources = [
            item
            for item in config.get("setupResources") or []
            if isinstance(item, dict)
        ]
        self.update_spec = (
            dict(config.get("updateSpec") or {})
            if isinstance(config.get("updateSpec"), dict)
            else {}
        )
        self.update_mode = str(
            config.get("updateMode") or "in-place"
        )
        self.state_machine_status = bool(
            config.get("stateMachineStatus", False)
        )
        self.finalizer = str(config.get("finalizer") or "")
        self.initial_assertions = [
            {
                "resource": str(item.get("resource") or ""),
                "name": str(item.get("name") or self.sample_name),
                "path": str(item.get("path") or ""),
                "equals": item.get("equals"),
            }
            for item in config.get("initialAssertions") or []
            if isinstance(item, dict)
            and item.get("resource")
            and item.get("path")
        ]
        self.drift_assertions = [
            {
                "resource": str(item.get("resource") or ""),
                "name": str(item.get("name") or self.sample_name),
                "path": str(item.get("path") or ""),
                "equals": item.get("equals"),
            }
            for item in config.get("driftAssertions") or []
            if isinstance(item, dict)
            and item.get("resource")
            and item.get("path")
        ]
        self.update_assertions = [
            {
                "resource": str(item.get("resource") or ""),
                "name": str(item.get("name") or self.sample_name),
                "path": str(item.get("path") or ""),
                "equals": item.get("equals"),
            }
            for item in config.get("updateAssertions") or []
            if isinstance(item, dict)
            and item.get("resource")
            and item.get("path")
        ]
        self._rbac_checks = [
            {
                "verb": str(item.get("verb") or "get"),
                "resource": str(item.get("resource") or ""),
                "apiGroup": str(item.get("apiGroup") or ""),
            }
            for item in config.get("rbacChecks") or []
            if isinstance(item, dict) and item.get("resource")
        ]

    def planned_steps(
        self,
        include_prepare: bool,
        include_lifecycle: bool,
    ) -> list[dict[str, Any]]:
        steps = []
        if include_prepare:
            steps.append(
                {
                    "name": "verify-existing-controller",
                    "validator": self.name,
                }
            )
            if self.drift_assertions:
                steps.append(
                    {
                        "name": "verify-drift-recovery",
                        "mutating": True,
                        "validator": self.name,
                    }
                )
        steps.extend([
            {"name": "apply-setup-resources", "validator": self.name},
            {"name": "verify-managed-resources", "validator": self.name},
        ])
        if include_lifecycle:
            steps.append(
                {
                    "name": "verify-idempotency",
                    "mutating": True,
                    "validator": self.name,
                }
            )
            if self.update_spec:
                steps.append(
                    {
                        "name": "verify-update",
                        "mutating": True,
                        "validator": self.name,
                    }
                )
            steps.extend(
                {"name": name, "mutating": True, "validator": self.name}
                for name in ("verify-delete", "restore-sample")
            )
        return steps

    def prepare(self, engine: DeploymentEngine) -> None:
        engine.checks["controllerPrepared"] = {
            "changed": False,
            "reason": "managed-resources validator uses the existing controller",
        }

    def verify_initial(self, engine: DeploymentEngine) -> None:
        self.apply_setup_resources(engine)
        engine.failed_step = "apply-sample"
        engine.run_cmd(
            "kubectl-apply-sample",
            self.kubectl(["apply", "-f", str(engine.sample)]),
            timeout=120,
        )
        managed = [
            self.wait_present(engine, item["resource"], item["name"])
            for item in self.managed_resources
        ]
        custom_resource = self.wait_present(
            engine,
            self.resource,
            self.sample_name,
        )
        status = custom_resource.get("status") or {}
        if self.status_phases:
            deadline = time.time() + engine.timeout_seconds
            while (
                str(status.get("phase") or "") not in self.status_phases
                and time.time() < deadline
            ):
                time.sleep(2)
                custom_resource = self.wait_present(
                    engine,
                    self.resource,
                    self.sample_name,
                )
                status = custom_resource.get("status") or {}
            if str(status.get("phase") or "") not in self.status_phases:
                raise RuntimeError(
                    f"Custom Resource phase was not accepted: {status}"
                )
        if self.state_machine_status:
            deadline = time.time() + engine.timeout_seconds
            last_error: RuntimeError | None = None
            while time.time() < deadline:
                status = custom_resource.get("status") or {}
                try:
                    self.verify_state_machine_status(custom_resource, status)
                    last_error = None
                    break
                except RuntimeError as error:
                    last_error = error
                    time.sleep(2)
                    custom_resource = self.wait_present(
                        engine,
                        self.resource,
                        self.sample_name,
                    )
            if last_error is not None:
                raise last_error
        engine.checks["managedResources"] = managed
        engine.checks["customResourceStatus"] = status
        if self.finalizer:
            finalizers = list(
                (custom_resource.get("metadata") or {}).get(
                    "finalizers"
                )
                or []
            )
            if self.finalizer not in finalizers:
                raise RuntimeError(
                    "Expected managed-resource finalizer was not registered: "
                    f"expected={self.finalizer}, actual={finalizers}"
                )
            engine.checks["finalizerRegistration"] = {
                "name": self.finalizer,
                "registered": True,
                "actual": finalizers,
            }
        if self.state_machine_status:
            engine.checks["stateMachineStatus"] = {
                "observedGeneration": status.get(
                    "observedGeneration"
                ),
                "conditions": status.get("conditions") or [],
            }
        if self.initial_assertions:
            engine.checks["initialAssertions"] = [
                self.wait_assertion(engine, item)
                for item in self.initial_assertions
            ]

    def verify_lifecycle(self, engine: DeploymentEngine) -> None:
        self.verify_idempotency(engine)
        if self.drift_assertions:
            self.verify_drift_recovery(engine)
        if self.update_spec:
            self.verify_update(engine)
        engine.failed_step = "verify-delete"
        engine.run_cmd(
            "kubectl-delete-custom-resource",
            self.kubectl(
                [
                    "delete",
                    self.resource,
                    self.sample_name,
                    "--ignore-not-found",
                ]
            ),
            timeout=120,
        )
        managed_results = {}
        for item in self.managed_resources:
            key = f"{item['resource']}/{item['name']}"
            if item["deletionPolicy"] == "retain":
                managed_results[key] = {
                    "expected": "present",
                    "passed": bool(
                        self.wait_present(
                            engine,
                            item["resource"],
                            item["name"],
                        )
                    ),
                }
            else:
                managed_results[key] = {
                    "expected": "absent",
                    "passed": self.wait_absent(
                        engine,
                        item["resource"],
                        item["name"],
                    ),
                }
        engine.checks["lifecycleDelete"] = {
            "customResourceAbsent": self.wait_absent(
                engine,
                self.resource,
                self.sample_name,
            ),
            "managedResources": managed_results,
        }
        if self.finalizer:
            engine.checks["finalizerLifecycle"] = {
                "name": self.finalizer,
                "registeredBeforeDelete": True,
                "customResourceRemoved": bool(
                    engine.checks["lifecycleDelete"][
                        "customResourceAbsent"
                    ]
                ),
                "explicitResourcesRemoved": all(
                    item.get("passed")
                    for item in managed_results.values()
                    if item.get("expected") == "absent"
                ),
            }
        engine.failed_step = "restore-sample"
        self.verify_initial(engine)
        engine.checks["lifecycleRestore"] = {"restored": True}

    def verify_state_machine_status(
        self,
        custom_resource: dict[str, Any],
        status: dict[str, Any],
    ) -> None:
        generation = int(
            (custom_resource.get("metadata") or {}).get("generation") or 0
        )
        observed = int(status.get("observedGeneration") or 0)
        if generation <= 0 or observed != generation:
            raise RuntimeError(
                "observedGeneration does not match metadata.generation: "
                f"generation={generation}, observed={observed}"
            )
        conditions = status.get("conditions") or []
        ready = next(
            (
                item
                for item in conditions
                if isinstance(item, dict)
                and item.get("type") == "Ready"
            ),
            None,
        )
        if not ready or ready.get("status") != "True":
            raise RuntimeError(
                f"Ready condition was not true: {conditions}"
            )
        if int(ready.get("observedGeneration") or 0) != generation:
            raise RuntimeError(
                "Ready condition observedGeneration does not match "
                f"metadata.generation: {ready}"
            )
    def verify_update(self, engine: DeploymentEngine) -> None:
        engine.failed_step = "verify-update"
        patch_payload = json.dumps(
            {"spec": self.update_spec},
            separators=(",", ":"),
        )
        engine.run_cmd(
            "kubectl-patch-custom-resource",
            self.kubectl(
                [
                    "patch",
                    self.resource,
                    self.sample_name,
                    "--type",
                    "merge",
                    "-p",
                    patch_payload,
                ]
            ),
            timeout=120,
        )
        assertions = [
            self.wait_assertion(engine, item)
            for item in self.update_assertions
        ]
        engine.checks["lifecycleUpdate"] = {
            "specPatch": self.update_spec,
            "mode": self.update_mode,
            "assertions": assertions,
        }

    def verify_idempotency(self, engine: DeploymentEngine) -> None:
        engine.failed_step = "verify-idempotency"
        before = {
            f"{item['resource']}/{item['name']}": normalized_resource_snapshot(
                self.wait_present(
                    engine,
                    item["resource"],
                    item["name"],
                )
            )
            for item in self.managed_resources
        }
        engine.run_cmd(
            "kubectl-reapply-sample",
            self.kubectl(["apply", "-f", str(engine.sample)]),
            timeout=120,
        )
        deadline = time.time() + engine.timeout_seconds
        after: dict[str, Any] = {}
        while time.time() < deadline:
            after = {
                f"{item['resource']}/{item['name']}": (
                    normalized_resource_snapshot(
                        self.wait_present(
                            engine,
                            item["resource"],
                            item["name"],
                        )
                    )
                )
                for item in self.managed_resources
            }
            if after == before:
                break
            time.sleep(2)
        if after != before:
            raise RuntimeError(
                "Managed resource desired state changed after reapplying "
                f"the same sample: before={before}, after={after}"
            )
        engine.checks["lifecycleIdempotency"] = {
            "reapplyStable": True,
            "resources": sorted(before),
        }

    def verify_drift_recovery(self, engine: DeploymentEngine) -> None:
        engine.failed_step = "verify-drift-recovery"
        assertion = self.drift_assertions[0]
        expected = assertion["equals"]
        drifted = drift_value(
            expected,
            resource=assertion["resource"],
            path=assertion["path"],
        )
        patch = json.dumps(
            [
                {
                    "op": "replace",
                    "path": json_pointer(assertion["path"]),
                    "value": drifted,
                }
            ],
            separators=(",", ":"),
        )
        engine.run_cmd(
            "kubectl-inject-managed-resource-drift",
            self.kubectl(
                [
                    "patch",
                    assertion["resource"],
                    assertion["name"],
                    "--type=json",
                    "-p",
                    patch,
                ]
            ),
            timeout=120,
        )
        recovered = self.wait_assertion(engine, assertion)
        engine.checks["lifecycleDriftRecovery"] = {
            "resource": assertion["resource"],
            "name": assertion["name"],
            "path": assertion["path"],
            "driftedValue": drifted,
            "expectedValue": expected,
            "recovered": bool(recovered.get("passed")),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "customResource": {
                "resource": self.resource,
                "name": self.sample_name,
                "namespace": self.namespace,
            },
            "managedResources": self.managed_resources,
            "initialAssertions": self.initial_assertions,
            "driftAssertions": self.drift_assertions,
            "updateSpec": self.update_spec,
            "updateAssertions": self.update_assertions,
            "updateMode": self.update_mode,
            "stateMachineStatus": self.state_machine_status,
            "finalizer": self.finalizer,
        }

    def rbac_checks(self) -> list[dict[str, str]]:
        return self._rbac_checks

    def apply_setup_resources(self, engine: DeploymentEngine) -> None:
        for index, item in enumerate(self.setup_resources, start=1):
            manifest = engine.log_dir / f"setup-resource-{index}.yaml"
            manifest.write_text(
                yaml.safe_dump(item, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            engine.run_cmd(
                f"kubectl-apply-setup-{index}",
                self.kubectl(["apply", "-f", str(manifest)]),
                timeout=120,
            )

    def wait_present(
        self,
        engine: DeploymentEngine,
        resource: str,
        name: str,
    ) -> dict[str, Any]:
        deadline = time.time() + engine.timeout_seconds
        last = ""
        while time.time() < deadline:
            result = engine.run_cmd(
                f"kubectl-get-{resource.replace('/', '-')}-{name}",
                self.kubectl(["get", resource, name, "-o", "json"]),
                check=False,
            )
            last = result.get("stderr") or result.get("stdout") or ""
            if result["exitCode"] == 0:
                return parse_json(result["stdout"])
            time.sleep(2)
        raise RuntimeError(f"{resource}/{name} was not created: {last}")

    def wait_absent(
        self,
        engine: DeploymentEngine,
        resource: str,
        name: str,
    ) -> bool:
        deadline = time.time() + engine.timeout_seconds
        while time.time() < deadline:
            result = engine.run_cmd(
                f"kubectl-get-{resource.replace('/', '-')}-{name}-absent",
                self.kubectl(["get", resource, name, "-o", "json"]),
                check=False,
            )
            if result["exitCode"] != 0 and is_not_found(result):
                return True
            time.sleep(2)
        return False

    def wait_assertion(
        self,
        engine: DeploymentEngine,
        assertion: dict[str, Any],
    ) -> dict[str, Any]:
        deadline = time.time() + engine.timeout_seconds
        last = None
        while time.time() < deadline:
            value = get_path(
                self.wait_present(
                    engine,
                    assertion["resource"],
                    assertion["name"],
                ),
                assertion["path"],
            )
            last = value
            if value == assertion["equals"]:
                return {**assertion, "actual": value, "passed": True}
            time.sleep(2)
        raise RuntimeError(
            "Managed resource assertion failed: "
            f"{assertion['resource']}/{assertion['name']} "
            f"{assertion['path']} expected={assertion['equals']!r} "
            f"actual={last!r}"
        )

    def kubectl(self, arguments: list[str]) -> list[str]:
        command = ["kubectl"]
        if self.namespace:
            command.extend(["--namespace", self.namespace])
        return [*command, *arguments]


def create_validator(name: str, config: dict[str, Any]) -> DeploymentValidator:
    if name == AppConfigConfigMapValidator.name:
        return AppConfigConfigMapValidator(config)
    if name == ManagedResourceValidator.name:
        return ManagedResourceValidator(config)
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
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def get_path(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
        if not match or not isinstance(current, dict):
            return None
        key, index = match.groups()
        if key not in current:
            return None
        current = current[key]
        if index is not None:
            if not isinstance(current, list):
                return None
            position = int(index)
            if position >= len(current):
                return None
            current = current[position]
    return current


def json_pointer(path: str) -> str:
    parts: list[str] = []
    for segment in path.split("."):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", segment)
        if not match:
            raise ValueError(f"unsupported assertion path: {path}")
        key, index = match.groups()
        parts.append(key.replace("~", "~0").replace("/", "~1"))
        if index is not None:
            parts.append(index)
    return "/" + "/".join(parts)


def drift_value(
    value: Any,
    *,
    resource: str = "",
    path: str = "",
) -> Any:
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 37
    if isinstance(value, str):
        return value + "-drift"
    if isinstance(value, dict):
        if value:
            result = dict(value)
            first = next(iter(result))
            if resource == "secret" and path == "data":
                result[first] = base64.b64encode(b"drift").decode("ascii")
            else:
                result[first] = drift_value(result[first])
            return result
        return {"drift": "injected"}
    if isinstance(value, list):
        return [] if value else ["drift"]
    raise ValueError(f"unsupported drift value: {value!r}")


def normalized_resource_snapshot(
    value: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(value.get("metadata") or {})
    for key in (
        "creationTimestamp",
        "generation",
        "managedFields",
        "resourceVersion",
        "uid",
    ):
        metadata.pop(key, None)
    return {
        "apiVersion": value.get("apiVersion"),
        "kind": value.get("kind"),
        "metadata": metadata,
        "spec": value.get("spec"),
        "data": value.get("data"),
        "stringData": value.get("stringData"),
    }


def is_not_found(result: dict[str, Any]) -> bool:
    text = f"{result.get('stdout', '')}\n{result.get('stderr', '')}"
    return "NotFound" in text or "not found" in text


def relative(path: Path) -> str:
    repo_root = Path(__file__).resolve().parents[2]
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)
