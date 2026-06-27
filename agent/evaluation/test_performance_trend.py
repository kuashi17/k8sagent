"""Tests for persisted regression performance history."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.evaluation.performance_trend import (
    write_performance_trend,
)


class PerformanceTrendTest(unittest.TestCase):
    def test_history_file_becomes_next_run_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history = root / "history" / "quick.json"
            first = write_performance_trend(
                root / "first",
                summary(1.5),
                history,
            )
            second = write_performance_trend(
                root / "second",
                summary(2.5),
                history,
            )

        self.assertEqual(first["previous"], {})
        self.assertEqual(second["previous"]["totalSeconds"], 1.5)
        self.assertEqual(second["current"]["totalSeconds"], 2.5)


def summary(seconds: float) -> dict[str, object]:
    return {
        "suite": "quick",
        "status": "passed",
        "checks": [
            {
                "name": "unit-tests",
                "elapsedSeconds": seconds,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
