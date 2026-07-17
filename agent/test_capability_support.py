"""Tests for evidence-backed capability support metadata."""

from __future__ import annotations

import unittest

from agent.capability_support import load_capability_support, support_for


class CapabilitySupportTest(unittest.TestCase):
    def test_level_follows_managed_resource_not_custom_resource_name(self) -> None:
        levels = {
            item["resource"]: item["level"]
            for item in support_for(["Deployment", "NetworkPolicy"])
        }

        self.assertEqual(levels["Deployment"], "stable")
        self.assertEqual(levels["NetworkPolicy"], "stable")

    def test_resource_specific_evidence_overrides_global_metadata(self) -> None:
        load_capability_support.cache_clear()
        support = load_capability_support()["ConfigMap"]

        self.assertEqual(support.level, "stable")
        self.assertEqual(support.evidence["source"], "kind-matrix")
        self.assertEqual(
            support.lastValidatedAt,
            "2026-07-17T14:38:02+09:00",
        )
        self.assertIsNone(support.evidenceRun)
        self.assertEqual(support.limitations, [])

    def test_resource_without_kind_evidence_has_no_runtime_date(self) -> None:
        load_capability_support.cache_clear()
        support = load_capability_support()["HorizontalPodAutoscaler"]

        self.assertEqual(support.level, "experimental")
        self.assertEqual(support.lastValidatedAt, "")
        self.assertEqual(
            support.evidence["source"],
            "capability-catalog",
        )


if __name__ == "__main__":
    unittest.main()
