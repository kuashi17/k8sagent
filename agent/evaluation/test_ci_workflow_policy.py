"""Regression tests for the cost-aware CI tier policy."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def workflow(name: str) -> dict:
    return yaml.load(
        (ROOT / ".github" / "workflows" / name).read_text(
            encoding="utf-8"
        ),
        Loader=yaml.BaseLoader,
    )


class CIWorkflowPolicyTest(unittest.TestCase):
    def test_quick_is_the_pull_request_gate(self) -> None:
        triggers = workflow("quick.yml")["on"]

        self.assertIn("pull_request", triggers)
        self.assertNotIn("push", triggers)

    def test_standard_runs_on_main_and_schedule(self) -> None:
        triggers = workflow("standard.yml")["on"]

        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertIn("schedule", triggers)

    def test_full_is_an_explicit_release_gate(self) -> None:
        data = workflow("full.yml")
        triggers = data["on"]

        self.assertEqual(set(triggers), {"workflow_dispatch"})
        self.assertIn("release_ref", triggers["workflow_dispatch"]["inputs"])
        steps = data["jobs"]["full"]["steps"]
        self.assertTrue(any(
            step.get("name") == "Verify compile and kind reuse contract"
            for step in steps
        ))


if __name__ == "__main__":
    unittest.main()
