"""Tests for catalog adapters and cross-capability policies."""

from __future__ import annotations

import unittest

from agent.tools.capability_adapter import adapt_capability
from agent.tools.capability_validation_policy import (
    validate_mutation_contract,
)
from agent.tools.controller_ir import FieldMapping, StaticMutation
from agent.tools.resource_catalog import load_resource_catalog


class CapabilityAdapterTest(unittest.TestCase):
    def test_deployment_port_scaffold_is_only_added_for_port_fields(self) -> None:
        catalog = load_resource_catalog()
        definition = catalog.by_name()["Deployment"]

        without_port = adapt_capability(
            definition,
            catalog.primitives_by_name(),
            {"image", "replicas"},
            [],
            catalog.by_name(),
        )
        with_port = adapt_capability(
            definition,
            catalog.primitives_by_name(),
            {"image", "replicas", "port"},
            [],
            catalog.by_name(),
        )

        base_container = without_port.base_object["spec"]["template"]["spec"]["containers"][0]
        port_container = with_port.base_object["spec"]["template"]["spec"]["containers"][0]
        self.assertNotIn("ports", base_container)
        self.assertEqual(port_container["ports"], [{"containerPort": 1}])

    def test_conditional_catalog_object_is_resolved_before_rendering(self) -> None:
        catalog = load_resource_catalog()
        definition = catalog.by_name()["StatefulSet"]

        adapted = adapt_capability(
            definition,
            catalog.primitives_by_name(),
            {"storageSize"},
            [],
            catalog.by_name(),
        )

        self.assertIn(
            "volumeClaimTemplates",
            adapted.base_object["spec"],
        )

    def test_conflicting_mutations_are_rejected_by_policy(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting Deployment"):
            validate_mutation_contract(
                "Deployment",
                [
                    FieldMapping(
                        source_path="spec.image",
                        target_path="spec.template.image",
                    )
                ],
                [
                    StaticMutation(
                        target_path="spec.template.image",
                        value="nginx",
                    )
                ],
            )


if __name__ == "__main__":
    unittest.main()
