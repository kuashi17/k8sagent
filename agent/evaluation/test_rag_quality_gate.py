"""Tests for the offline RAG quality gate thresholds."""

from __future__ import annotations

import unittest

from agent.evaluation.rag_quality_gate import passes_thresholds


class RagQualityGateTest(unittest.TestCase):
    def test_all_quality_thresholds_must_pass(self) -> None:
        thresholds = {
            "minHitAt3": 0.8,
            "minRecallAt3": 0.45,
            "minMrr": 0.5,
        }

        self.assertTrue(
            passes_thresholds(
                {"hitAt3": 1.0, "recallAt3": 0.48, "mrr": 0.57},
                thresholds,
            )
        )
        self.assertFalse(
            passes_thresholds(
                {"hitAt3": 1.0, "recallAt3": 0.3, "mrr": 0.57},
                thresholds,
            )
        )


if __name__ == "__main__":
    unittest.main()
