"""Tests for reliability section aggregation."""

from __future__ import annotations

import unittest

from agent.evaluation.reliability_test_runner import overall_status


class ReliabilityStatusTest(unittest.TestCase):
    def test_skipped_optional_kind_context_does_not_fail_suite(self) -> None:
        self.assertEqual(
            overall_status(
                {"status": "passed"},
                {"status": "passed"},
                {"status": "skipped", "reason": "context unavailable"},
            ),
            "passed",
        )


if __name__ == "__main__":
    unittest.main()
