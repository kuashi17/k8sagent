"""Tests for the external managed-resource capability catalog."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.tools.resource_catalog import load_resource_catalog


class ResourceCatalogTest(unittest.TestCase):
    def test_catalog_is_validated_and_aliases_are_indexed(self) -> None:
        catalog = load_resource_catalog()

        self.assertGreaterEqual(catalog.version, 1)
        self.assertEqual(
            catalog.by_name()["PVC"].kind,
            "PersistentVolumeClaim",
        )
        self.assertIn(
            "spec",
            catalog.by_name()["DaemonSet"].baseObject,
        )

    def test_invalid_catalog_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.yaml"
            path.write_text(
                "version: 1\nresources:\n  - kind: Broken\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_resource_catalog(path)

    def test_duplicate_alias_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
resources:
  - kind: First
    aliases: [Shared]
    apiVersion: v1
    suffix: first
  - kind: Second
    aliases: [Shared]
    apiVersion: v1
    suffix: second
"""
        )

    def test_invalid_nested_path_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
resources:
  - kind: Broken
    apiVersion: v1
    suffix: broken
    fieldMappings:
      - source: value
        target: spec.containers[x].image
"""
        )

    def test_malicious_resource_plural_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
resources:
  - kind: Broken
    apiVersion: v1
    plural: pods/status
    suffix: broken
"""
        )

    def test_identity_and_status_mutation_paths_are_rejected(self) -> None:
        for target in (
            "metadata.ownerReferences",
            "metadata.finalizers[0]",
            "metadata.namespace",
            "status.phase",
        ):
            with self.subTest(target=target):
                self.assert_invalid(
                    f"""version: 1
resources:
  - kind: Broken
    apiVersion: v1
    suffix: broken
    fieldMappings:
      - source: value
        target: {target}
"""
                )

    def test_incomplete_dependency_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
resources:
  - kind: Broken
    apiVersion: v1
    suffix: broken
    dependencyKind: Service
"""
        )

    def test_unknown_dependency_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
resources:
  - kind: Workload
    apiVersion: apps/v1
    suffix: workload
    dependencyKind: Missing
    dependencyVariable: missingName
    dependencyTargetPath: spec.missingName
"""
        )

    def test_base_object_cannot_override_identity(self) -> None:
        self.assert_invalid(
            """version: 1
resources:
  - kind: Unsafe
    apiVersion: v1
    suffix: unsafe
    baseObject:
      metadata:
        namespace: another-namespace
"""
        )

    def test_unknown_behavior_binding_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
resources:
  - kind: Broken
    apiVersion: v1
    suffix: broken
    behaviorBindings:
      - primitive: missing
        paths: {}
"""
        )

    def test_missing_behavior_path_binding_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
behaviorPrimitives:
  - name: env
    activationFields: [env]
    mutations:
      - source: env
        target: "{container}.env"
        transform: env-map
resources:
  - kind: Broken
    apiVersion: v1
    suffix: broken
    behaviorBindings:
      - primitive: env
        paths: {}
"""
        )

    def test_invalid_behavior_target_template_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
behaviorPrimitives:
  - name: broken
    activationFields: [value]
    mutations:
      - source: value
        target: "{container.spec.value"
resources:
  - kind: Example
    apiVersion: v1
    suffix: example
"""
        )

    def test_duplicate_bound_behavior_target_is_rejected(self) -> None:
        self.assert_invalid(
            """version: 1
behaviorPrimitives:
  - name: first
    activationFields: [first]
    mutations:
      - source: first
        target: "{container}.env"
  - name: second
    activationFields: [second]
    mutations:
      - source: second
        target: "{container}.env"
resources:
  - kind: Broken
    apiVersion: v1
    suffix: broken
    behaviorBindings:
      - primitive: first
        paths: {container: spec.containers[0]}
      - primitive: second
        paths: {container: spec.containers[0]}
"""
        )

    def assert_invalid(self, text: str) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.yaml"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_resource_catalog(path)


if __name__ == "__main__":
    unittest.main()
