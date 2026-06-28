"""Tests for profile-less Controller rendering."""

from __future__ import annotations

import unittest

from agent.tools.controller_pipeline import generate_controller


def render_controller(model: dict) -> str:
    return generate_controller(model)[1]


def model(resources, spec_fields, status_fields):
    return {
        "project": {"module": "sample.io/example-operator"},
        "api": {
            "kind": "Example",
            "group": "apps",
            "version": "v1alpha1",
        },
        "controller": {"managedResources": resources},
        "specFields": [{"name": name} for name in spec_fields],
        "statusFields": [
            {
                "name": name,
                "type": (
                    "int32"
                    if name == "readyReplicas"
                    else "metav1.Time"
                    if name == "lastScheduleTime"
                    else "string"
                ),
            }
            for name in status_fields
        ],
        "rbacResources": [
            {
                "apiGroup": "apps.sample.io",
                "resource": "examples",
                "verbs": ["get", "list", "watch"],
            }
        ],
    }


class ControllerRendererTest(unittest.TestCase):
    def test_state_machine_status_and_requeue_are_rendered(self) -> None:
        rendered = render_controller(
            model(
                ["ConfigMap"],
                ["data"],
                [
                    "phase",
                    "message",
                    "observedGeneration",
                    "conditions",
                ],
            )
        )

        self.assertIn("instance.Status.ObservedGeneration", rendered)
        self.assertIn("meta.SetStatusCondition", rendered)
        self.assertIn("ObservedGeneration: instance.Generation", rendered)
        self.assertIn("RequeueAfter: 30 * time.Second", rendered)
        self.assertIn('"Recreating"', rendered)

    def test_explicit_delete_resource_uses_finalizer(self) -> None:
        rendered = render_controller(
            model(
                ["ClusterRole"],
                ["clusterRoleName", "ruleVerbs"],
                ["phase", "message"],
            )
        )

        self.assertIn("const managedFinalizer", rendered)
        self.assertIn(
            'const managedFinalizer = "apps/example-finalizer"',
            rendered,
        )
        self.assertIn("controllerutil.AddFinalizer", rendered)
        self.assertIn("finalizeManagedResources", rendered)
        self.assertIn("finalize ClusterRole", rendered)
        self.assertNotIn("setOwner(instance, object", rendered)

    def test_deployment_and_service_behavior_is_rendered(self) -> None:
        rendered = render_controller(
            model(
                ["Deployment", "Service"],
                ["image", "replicas", "port"],
                [
                    "phase",
                    "deploymentName",
                    "serviceName",
                    "readyReplicas",
                    "message",
                ],
            )
        )
        self.assertIn("reconcileDeployment", rendered)
        self.assertIn("reconcileService", rendered)
        self.assertIn("CreateOrUpdate", rendered)
        self.assertIn("Status().Update", rendered)
        self.assertIn("SetControllerReference", rendered)
        self.assertIn(
            'unstructured.NestedInt64(deploymentReadyReplicasObject.Object, "status", "readyReplicas")',
            rendered,
        )
        self.assertIn(
            'if names["Deployment"] != ""',
            rendered,
        )
        self.assertIn(
            'Owns(managedObject("apps", "v1", "Deployment", "", ""))',
            rendered,
        )
        self.assertIn(
            'Owns(managedObject("", "v1", "Service", "", ""))',
            rendered,
        )
        self.assertIn(
            '[]interface{}{"spec", "selector", "matchLabels"}',
            rendered,
        )
        self.assertIn(
            '[]interface{}{"spec", "selector"}',
            rendered,
        )
        self.assertIn(
            "func stringMapToInterface",
            rendered,
        )

    def test_namespace_policy_updates_labels_without_owner_reference(self) -> None:
        rendered = render_controller(
            model(
                ["Namespace"],
                ["namespaceName", "labels"],
                ["phase", "observedNamespace", "message"],
            )
        )
        namespace_function = rendered.split(
            "func (r *ExampleReconciler) reconcileNamespace",
            1,
        )[1].split("func ", 1)[0]
        self.assertIn("object.SetLabels(labels)", namespace_function)
        self.assertIn("mergeStringMapAtPath", namespace_function)
        self.assertIn("r.Get(", namespace_function)
        self.assertIn("r.Update(", namespace_function)
        self.assertNotIn("CreateOrUpdate", namespace_function)
        self.assertNotIn("setOwner(", namespace_function)
        self.assertNotIn(
            'Owns(managedObject("", "v1", "Namespace", "", ""))',
            rendered,
        )

    def test_enabled_false_deletes_managed_secret(self) -> None:
        rendered = render_controller(
            model(
                ["Secret"],
                ["secretName", "data", "enabled"],
                ["phase", "secretName", "message"],
            )
        )
        self.assertIn("if !instance.Spec.Enabled", rendered)
        self.assertIn("r.Delete(ctx, object)", rendered)

    def test_metav1_time_status_mapping_adds_time_conversion(self) -> None:
        rendered = render_controller(
            model(
                ["CronJob"],
                ["schedule", "image"],
                ["phase", "cronJobName", "lastScheduleTime", "message"],
            )
        )
        self.assertIn('"time"', rendered)
        self.assertIn(
            'metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"',
            rendered,
        )
        self.assertIn(
            'unstructured.NestedString(cronJobLastScheduleTimeObject.Object, "status", "lastScheduleTime")',
            rendered,
        )
        self.assertIn("metav1.NewTime(parsed)", rendered)

    def test_statefulset_storage_and_status_behavior_is_rendered(self) -> None:
        rendered = render_controller(
            model(
                ["StatefulSet", "Service"],
                ["size", "image", "storageSize", "port"],
                ["phase", "readyReplicas", "message"],
            )
        )

        self.assertIn("reconcileStatefulSet", rendered)
        self.assertIn('serviceName = instance.Name + "-service"', rendered)
        self.assertIn(
            '[]interface{}{"spec", "serviceName"}, serviceName',
            rendered,
        )
        self.assertIn(
            '[]interface{}{"spec", "replicas"}, int64(instance.Spec.Size)',
            rendered,
        )
        self.assertIn('"volumeClaimTemplates"', rendered)
        self.assertIn(
            '"requests", "storage"}, instance.Spec.StorageSize',
            rendered,
        )
        self.assertIn('"mountPath": "/data"', rendered)
        self.assertIn(
            '"containerPort"}, int64(instance.Spec.Port)',
            rendered,
        )
        self.assertIn(
            'unstructured.NestedInt64(statefulSetReadyReplicasObject.Object, "status", "readyReplicas")',
            rendered,
        )
        self.assertIn(
            'Owns(managedObject("apps", "v1", "StatefulSet", "", ""))',
            rendered,
        )

    def test_immutable_mapping_renders_controller_recreate_guard(
        self,
    ) -> None:
        rendered = render_controller(
            model(
                ["PersistentVolumeClaim"],
                [
                    "claimName",
                    "storageSize",
                    "storageClassName",
                    "accessModes",
                ],
                ["phase", "claimName", "message"],
            )
        )
        function = rendered.split(
            "func (r *ExampleReconciler) reconcilePersistentVolumeClaim",
            1,
        )[1].split("func ", 1)[0]

        self.assertIn("recreate := false", function)
        self.assertIn("delete immutable managed resource", function)
        self.assertIn(
            '[]interface{}{"spec", "accessModes"}',
            function,
        )

    def test_composable_container_primitives_are_rendered(self) -> None:
        rendered = render_controller(
            model(
                ["Deployment"],
                [
                    "image",
                    "env",
                    "resourceLimits",
                    "pvcName",
                    "mountPath",
                    "healthPath",
                    "healthPort",
                ],
                ["phase", "message"],
            )
        )

        self.assertIn("envMapToInterface(instance.Spec.Env)", rendered)
        self.assertIn(
            '"resources", "limits"}, stringMapToInterface',
            rendered,
        )
        self.assertIn(
            '"persistentVolumeClaim", "claimName"}, instance.Spec.PVCName',
            rendered,
        )
        self.assertIn(
            '"volumeMounts", 0, "name"}, "workload-data"',
            rendered,
        )
        self.assertIn(
            '"livenessProbe", "httpGet", "port"}, int64(instance.Spec.HealthPort)',
            rendered,
        )


if __name__ == "__main__":
    unittest.main()
