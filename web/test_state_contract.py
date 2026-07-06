"""Tests for unambiguous user-visible workflow states."""

from __future__ import annotations

import unittest

from web.state_contract import workflow_state


class WorkflowStateContractTest(unittest.TestCase):
    def test_requirement_state_transitions_do_not_mix_outcomes(self) -> None:
        cases = [
            (
                {"state": "queued", "jobType": "requirement"},
                "approved",
            ),
            (
                {"state": "running", "jobType": "requirement", "phase": "artifact patch"},
                "generating",
            ),
            (
                {
                    "state": "succeeded",
                    "jobType": "requirement",
                    "summary": {"agentMode": "dry-run"},
                },
                "planned",
            ),
            (
                {
                    "state": "succeeded",
                    "jobType": "requirement",
                    "summary": {"agentMode": "execute"},
                },
                "generated",
            ),
            (
                {
                    "state": "succeeded",
                    "jobType": "requirement",
                    "summary": {"runStatus": "clarification-required"},
                },
                "clarification-required",
            ),
            (
                {
                    "state": "failed",
                    "jobType": "requirement",
                    "summary": {"recovery": {"plan": {"classification": "rbac"}}},
                },
                "recovery-proposed",
            ),
        ]

        for job, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(workflow_state(job), expected)

    def test_kind_failure_never_becomes_kind_passed(self) -> None:
        failed = {
            "state": "failed",
            "jobType": "kind-validation",
            "kindValidation": {
                "status": "failed",
                "results": [{"status": "failed"}],
            },
        }
        passed = {
            "state": "succeeded",
            "jobType": "kind-validation",
            "kindValidation": {
                "status": "passed",
                "results": [{"status": "passed"}],
            },
        }

        self.assertEqual(workflow_state(failed), "kind-failed")
        self.assertEqual(workflow_state(passed), "kind-passed")
        self.assertEqual(
            workflow_state({"state": "running", "jobType": "kind-validation"}),
            "kind-validating",
        )

    def test_log_analysis_has_a_separate_state(self) -> None:
        self.assertEqual(
            workflow_state({"state": "running", "jobType": "log-analysis"}),
            "log-analysis",
        )


if __name__ == "__main__":
    unittest.main()
