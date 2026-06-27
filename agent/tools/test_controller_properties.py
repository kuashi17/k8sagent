"""Property-style invariants for generalized Controller contracts."""

from __future__ import annotations

import random
import unittest

from agent.tools.controller_ir import (
    DeletionPolicy,
    FieldMutability,
    OwnershipPolicy,
    UpdatePolicy,
)
from agent.tools.controller_ir_builder import build_controller_ir
from agent.tools.controller_renderer import render_controller
from agent.tools.resource_catalog import load_resource_catalog


class ControllerPropertyTest(unittest.TestCase):
    def test_catalog_lifecycle_contracts_are_safe(self) -> None:
        for definition in load_resource_catalog().resources:
            with self.subTest(kind=definition.kind):
                if definition.ownership == OwnershipPolicy.FINALIZER:
                    self.assertEqual(
                        definition.deletionPolicy,
                        DeletionPolicy.EXPLICIT_DELETE,
                    )
                if definition.ownership == OwnershipPolicy.NONE:
                    self.assertEqual(
                        definition.deletionPolicy,
                        DeletionPolicy.RETAIN,
                    )
                for mapping in definition.fieldMappings:
                    if mapping.mutability == FieldMutability.IMMUTABLE:
                        self.assertEqual(
                            mapping.updatePolicy,
                            UpdatePolicy.RECREATE,
                        )

    def test_random_field_order_is_render_idempotent(self) -> None:
        catalog = load_resource_catalog()
        rng = random.Random(20260627)
        definitions = [
            item
            for item in catalog.resources
            if item.fieldMappings and item.strategy.value != "read-only"
        ]
        for _ in range(40):
            definition = rng.choice(definitions)
            by_target: dict[str, list[str]] = {}
            for mapping in definition.fieldMappings:
                by_target.setdefault(mapping.target, []).append(
                    mapping.source
                )
            fields = [
                rng.choice(candidates)
                for candidates in by_target.values()
            ]
            rng.shuffle(fields)
            first = self.model(definition.kind, fields)
            rng.shuffle(fields)
            second = self.model(definition.kind, fields)
            with self.subTest(kind=definition.kind, fields=fields):
                self.assertEqual(
                    build_controller_ir(first).to_dict(),
                    build_controller_ir(second).to_dict(),
                )
                self.assertEqual(
                    render_controller(first),
                    render_controller(first),
                )

    @staticmethod
    def model(kind: str, fields: list[str]) -> dict:
        return {
            "project": {"module": "sample.io/property-operator"},
            "api": {
                "kind": "PropertyPolicy",
                "group": "property",
                "version": "v1alpha1",
            },
            "controller": {"managedResources": [kind]},
            "specFields": [
                {"name": name, "type": "string"}
                for name in fields
            ],
            "statusFields": [
                {"name": "phase", "type": "string"},
                {"name": "message", "type": "string"},
            ],
            "rbacResources": [],
        }


if __name__ == "__main__":
    unittest.main()
