"""Tests for Kubernetes Discovery-backed capability validation."""

from __future__ import annotations

import unittest

from agent.tools.capability_discovery import (
    discovery_endpoint,
    validate_capability_discovery,
)
from agent.tools.controller_ir import ResourceScope
from agent.tools.resource_catalog import ResourceCapabilityDefinition


def reader(payload):
    return lambda endpoint: payload


class CapabilityDiscoveryTest(unittest.TestCase):
    def capability(self, **changes):
        values = {
            "kind": "Ingress",
            "apiVersion": "networking.k8s.io/v1",
            "suffix": "ingress",
        }
        values.update(changes)
        return ResourceCapabilityDefinition(**values)

    def payload(self, **changes):
        resource = {
            "name": "ingresses",
            "kind": "Ingress",
            "namespaced": True,
            "verbs": [
                "create",
                "delete",
                "get",
                "list",
                "patch",
                "update",
                "watch",
            ],
        }
        resource.update(changes)
        return {
            "groupVersion": "networking.k8s.io/v1",
            "resources": [resource],
        }

    def test_discovery_enriches_exact_plural_and_verbs(self) -> None:
        capability = self.capability()
        result = validate_capability_discovery(
            capability,
            reader(self.payload()),
        )

        self.assertEqual(discovery_endpoint("v1"), "/api/v1")
        self.assertEqual(
            discovery_endpoint("networking.k8s.io/v1"),
            "/apis/networking.k8s.io/v1",
        )
        self.assertEqual(capability.plural, "ingresses")
        self.assertEqual(result.resource, "ingresses")
        self.assertEqual(result.rbacApiGroup, "networking.k8s.io")
        self.assertEqual(result.rbacResource, "ingresses")
        self.assertIn("delete", result.requiredVerbs)

    def test_scope_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "scope mismatch"):
            validate_capability_discovery(
                self.capability(
                    scope=ResourceScope.CLUSTER,
                    ownership="none",
                    deletionPolicy="retain",
                ),
                reader(self.payload()),
            )

    def test_plural_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "plural mismatch"):
            validate_capability_discovery(
                self.capability(plural="ingressitems"),
                reader(self.payload()),
            )

    def test_missing_required_verb_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "required verbs.*delete"):
            validate_capability_discovery(
                self.capability(),
                reader(
                    self.payload(
                        verbs=[
                            "create",
                            "get",
                            "list",
                            "patch",
                            "update",
                            "watch",
                        ]
                    )
                ),
            )


if __name__ == "__main__":
    unittest.main()
