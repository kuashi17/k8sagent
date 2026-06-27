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
        self.assertEqual(
            catalog.by_name()["DaemonSet"].emitter,
            "generic-object",
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


if __name__ == "__main__":
    unittest.main()
