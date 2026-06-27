"""Tests for generalized spec to behavior-oriented Controller IR."""

from __future__ import annotations

import unittest

from agent.tools.controller_ir import (
    DeletionPolicy,
    OwnershipPolicy,
    ReconcileStrategy,
    ResourceCapability,
    ResourceScope,
    FieldMutability,
    UpdatePolicy,
)
from agent.tools.controller_ir_builder import build_controller_ir


def model(resources, spec_fields, status_fields, field_mappings=None):
    return {
        "project": {"module": "sample.io/example-operator"},
        "api": {
            "kind": "Example",
            "group": "apps",
            "version": "v1alpha1",
        },
        "controller": {
            "managedResources": resources,
            "fieldMappings": field_mappings or [],
        },
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
                "apiGroup": "apps",
                "resource": "deployments",
                "verbs": ["get", "list", "watch", "create", "update"],
            }
        ],
    }


class ControllerIRBuilderTest(unittest.TestCase):
    def test_create_or_update_resource_has_behavior_contract(self) -> None:
        ir = build_controller_ir(
            model(
                ["Deployment", "Service", "Pod"],
                ["appName", "image", "replicas", "port"],
                ["phase", "deploymentName", "serviceName", "readyReplicas"],
                [
                    {
                        "from": "spec.image",
                        "to": "Deployment container image",
                    }
                ],
            )
        )

        deployment = ir.resource("Deployment")
        self.assertIsNotNone(deployment)
        self.assertEqual(
            deployment.strategy,
            ReconcileStrategy.CREATE_OR_UPDATE,
        )
        self.assertEqual(
            deployment.ownership,
            OwnershipPolicy.OWNER_REFERENCE,
        )
        self.assertEqual(
            deployment.deletion_policy,
            DeletionPolicy.GARBAGE_COLLECT,
        )
        self.assertIn(ResourceCapability.CREATE, deployment.capabilities)
        self.assertIn("spec", deployment.base_object)
        self.assertEqual(
            deployment.update_policy,
            UpdatePolicy.IN_PLACE,
        )
        self.assertEqual(deployment.name.source_path, "spec.appName")
        self.assertTrue(
            any(
                item.target_path == "spec.replicas"
                for item in deployment.field_mappings
            )
        )
        self.assertFalse(
            any(
                item.target_path.startswith("Deployment.")
                for item in deployment.field_mappings
            )
        )
        self.assertTrue(
            any(
                item.target_path == "status.readyReplicas"
                and item.source_path == "status.readyReplicas"
                and item.target_type == "int32"
                for item in deployment.status_mappings
            )
        )

        pod = ir.resource("Pod")
        self.assertEqual(pod.strategy, ReconcileStrategy.READ_ONLY)
        self.assertNotIn(pod, ir.renderable_resources())

    def test_cluster_scoped_namespace_is_patch_and_retain(self) -> None:
        namespace = build_controller_ir(
            model(
                ["Namespace"],
                ["namespaceName", "labels"],
                ["phase", "observedNamespace", "message"],
            )
        ).resource("Namespace")

        self.assertEqual(namespace.scope, ResourceScope.CLUSTER)
        self.assertEqual(
            namespace.strategy,
            ReconcileStrategy.PATCH_EXISTING,
        )
        self.assertEqual(namespace.ownership, OwnershipPolicy.NONE)
        self.assertEqual(namespace.deletion_policy, DeletionPolicy.RETAIN)
        self.assertIn(
            ResourceCapability.PATCH_EXISTING,
            namespace.capabilities,
        )
        self.assertEqual(
            namespace.field_mappings[0].transform,
            "merge-string-map",
        )

    def test_enabled_resource_has_explicit_disable_condition(self) -> None:
        secret = build_controller_ir(
            model(
                ["Secret"],
                ["secretName", "data", "enabled"],
                ["phase", "secretName", "message"],
            )
        ).resource("Secret")

        self.assertEqual(secret.disable_when, "spec.enabled == false")
        self.assertEqual(
            secret.name.fallback_template,
            "{metadata.name}-secret",
        )

    def test_unsupported_managed_resource_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "unsupported managed resources: ReplicaSet",
        ):
            build_controller_ir(
                model(
                    ["ReplicaSet"],
                    ["image"],
                    ["phase"],
                )
            )

    def test_statefulset_behavior_is_derived_from_common_fields(self) -> None:
        statefulset = build_controller_ir(
            model(
                ["StatefulSet", "Service"],
                ["size", "image", "storageSize"],
                ["phase", "readyReplicas", "message"],
            )
        ).resource("StatefulSet")

        self.assertEqual(
            statefulset.strategy,
            ReconcileStrategy.CREATE_OR_UPDATE,
        )
        self.assertEqual(
            statefulset.ownership,
            OwnershipPolicy.OWNER_REFERENCE,
        )
        self.assertEqual(
            statefulset.dependency_target_path,
            "spec.serviceName",
        )
        self.assertIn(
            "volumeClaimTemplates",
            statefulset.base_object["spec"],
        )
        self.assertTrue(
            any(
                item.target_path == "spec.volumeClaimTemplates[0].spec.resources.requests.storage"
                for item in statefulset.field_mappings
            )
        )
        self.assertTrue(
            any(
                item.target_path == "status.readyReplicas"
                and item.target_type == "int32"
                for item in statefulset.status_mappings
            )
        )

    def test_composable_workload_behaviors_are_activated(self) -> None:
        deployment = build_controller_ir(
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
                [
                    {
                        "from": "spec.env",
                        "to": (
                            "Deployment.spec.template.spec."
                            "containers[0].env"
                        ),
                    }
                ],
            )
        ).resource("Deployment")

        self.assertEqual(
            set(deployment.active_behaviors),
            {
                "container-env",
                "resource-limits",
                "pvc-volume",
                "health-probe",
            },
        )
        mappings = {
            item.source_path: item
            for item in deployment.field_mappings
        }
        self.assertEqual(mappings["spec.env"].transform, "env-map")
        self.assertEqual(
            mappings["spec.resourceLimits"].target_path,
            "spec.template.spec.containers[0].resources.limits",
        )
        self.assertEqual(
            mappings["spec.pvcName"].target_path,
            "spec.template.spec.volumes[0].persistentVolumeClaim.claimName",
        )
        self.assertIn(
            "spec.template.spec.containers[0].volumeMounts[0].name",
            {
                item.target_path
                for item in deployment.static_mutations
            },
        )
    def test_immutable_fields_are_explicit_lifecycle_contracts(
        self,
    ) -> None:
        claim = build_controller_ir(
            model(
                ["PersistentVolumeClaim"],
                [
                    "claimName",
                    "storageSize",
                    "storageClassName",
                    "accessModes",
                ],
                ["phase", "claimName"],
            )
        ).resource("PersistentVolumeClaim")

        immutable = {
            item.target_path: item
            for item in claim.field_mappings
            if item.mutability == FieldMutability.IMMUTABLE
        }
        self.assertEqual(
            set(immutable),
            {"spec.storageClassName", "spec.accessModes"},
        )
        self.assertTrue(
            all(
                item.update_policy == UpdatePolicy.RECREATE
                for item in immutable.values()
            )
        )
        self.assertEqual(claim.update_policy, UpdatePolicy.RECREATE)


if __name__ == "__main__":
    unittest.main()
