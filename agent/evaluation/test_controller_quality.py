"""Tests for generated Controller quality scoring."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.evaluation.controller_quality import evaluate_controller_quality


REPO_ROOT = Path(__file__).resolve().parents[2]


class ControllerQualityTest(unittest.TestCase):
    def test_existing_appconfig_fixture_meets_quality_contract(self) -> None:
        result = evaluate_controller_quality(
            REPO_ROOT
            / "workspace"
            / "generated-operators"
            / "app-config-operator",
            REPO_ROOT / "generated" / "appconfig-operator-spec.yaml",
            [
                {
                    "tool": "validation",
                    "steps": [{"target": "test", "exitCode": 0}],
                }
            ],
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["score"], 100.0)

    def test_missing_project_is_reported_as_not_run(self) -> None:
        result = evaluate_controller_quality(
            REPO_ROOT / "workspace" / "generated-operators" / "missing",
            REPO_ROOT / "generated" / "missing.yaml",
        )
        self.assertEqual(result["status"], "not-run")
        self.assertEqual(result["score"], 0)


if __name__ == "__main__":
    unittest.main()
