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

    def assert_invalid(self, text: str) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.yaml"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                load_resource_catalog(path)


if __name__ == "__main__":
    unittest.main()
