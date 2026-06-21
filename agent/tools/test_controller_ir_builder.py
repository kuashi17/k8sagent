"""Tests for generalized spec to behavior-oriented Controller IR."""

from __future__ import annotations

import unittest

from agent.tools.controller_ir import (
    DeletionPolicy,
    OwnershipPolicy,
    ReconcileStrategy,
    ResourceCapability,
    ResourceScope,
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
        "statusFields": [{"name": name} for name in status_fields],
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
        self.assertEqual(deployment.name.source_path, "spec.appName")
        self.assertTrue(
            any(
                item.target_path == "spec.replicas"
                for item in deployment.field_mappings
            )
        )
        self.assertTrue(
            any(
                item.target_path == "status.readyReplicas"
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


if __name__ == "__main__":
    unittest.main()
