"""Tests for the unified evaluation report."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.evaluation.unified_evaluation import build_unified_evaluation


class UnifiedEvaluationTest(unittest.TestCase):
    def test_report_has_required_top_level_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "reliability").mkdir()
            (root / "rag-quality.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "metrics": {"hitAt3": 1.0},
                    }
                ),
                encoding="utf-8",
            )
            (root / "reliability" / "reliability-test-results.json").write_text(
                json.dumps(
                    {
                        "tests": [
                            {"name": "allowlist", "passed": True}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_unified_evaluation(root)

        self.assertEqual(
            set(payload),
            {
                "requirementUnderstanding",
                "ragQuality",
                "artifactQuality",
                "validationSuccess",
                "safetyReliability",
                "e2eSuccess",
                "latency",
                "overallScore",
            },
        )
        self.assertEqual(payload["ragQuality"]["score"], 100.0)
        self.assertEqual(payload["safetyReliability"]["score"], 100.0)


if __name__ == "__main__":
    unittest.main()
