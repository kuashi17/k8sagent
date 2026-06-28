"""Tests for Full CI timing aggregation."""

from __future__ import annotations

import unittest

from agent.evaluation.full_ci_timing import build_timing_report


class FullCITimingTest(unittest.TestCase):
    def test_report_separates_queue_job_regression_and_overhead(self) -> None:
        report = build_timing_report(
            {
                "id": 42,
                "html_url": "https://example.test/runs/42",
                "head_sha": "abc",
                "created_at": "2026-06-28T00:00:00Z",
            },
            {
                "name": "full",
                "conclusion": "success",
                "started_at": "2026-06-28T00:01:00Z",
                "completed_at": "2026-06-28T00:10:00Z",
                "steps": [
                    {
                        "name": "Set up job",
                        "conclusion": "success",
                        "started_at": "2026-06-28T00:01:00Z",
                        "completed_at": "2026-06-28T00:01:05Z",
                    },
                    {
                        "name": (
                            "Run python3 scripts/run-regression-tests.py "
                            "--suite full"
                        ),
                        "conclusion": "success",
                        "started_at": "2026-06-28T00:02:00Z",
                        "completed_at": "2026-06-28T00:09:00Z",
                    },
                ],
            },
            {
                "checks": [
                    {"name": "compile", "elapsedSeconds": 150},
                    {"name": "kind", "elapsedSeconds": 250},
                ]
            },
            600,
        )

        self.assertEqual(report["queueSeconds"], 60)
        self.assertEqual(report["jobSeconds"], 540)
        self.assertEqual(report["regressionSeconds"], 400)
        self.assertEqual(report["workflowOverheadSeconds"], 140)
        self.assertEqual(report["budgetStatus"], "passed")
        self.assertEqual(report["observedSeconds"], 600)
        self.assertEqual(report["overallBudgetStatus"], "passed")
        self.assertEqual(report["categories"]["regression"], 420)

    def test_job_over_ten_minutes_fails_budget(self) -> None:
        report = build_timing_report(
            {"created_at": "2026-06-28T00:00:00Z"},
            {
                "started_at": "2026-06-28T00:00:00Z",
                "completed_at": "2026-06-28T00:10:01Z",
                "steps": [],
            },
            {"checks": []},
            600,
        )

        self.assertEqual(report["budgetStatus"], "failed")

    def test_long_queue_fails_integrated_observation_budget(self) -> None:
        report = build_timing_report(
            {"created_at": "2026-06-28T00:00:00Z"},
            {
                "started_at": "2026-06-28T00:16:00Z",
                "completed_at": "2026-06-28T00:21:00Z",
                "steps": [],
            },
            {"checks": []},
            600,
            1200,
        )

        self.assertEqual(report["budgetStatus"], "passed")
        self.assertEqual(report["observedBudgetStatus"], "failed")


if __name__ == "__main__":
    unittest.main()
