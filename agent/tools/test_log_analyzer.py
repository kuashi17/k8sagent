"""Tests for deterministic Agent summary log classification."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.tools.log_analyzer import analyze_summary


class LogAnalyzerTest(unittest.TestCase):
    def test_agent_tool_failure_is_normalized_and_classified(self) -> None:
        analysis = analyze_summary(
            Path("logs/agent/example"),
            {
                "toolResults": [
                    {
                        "tool": "spec_generator",
                        "status": "failed",
                        "exitCode": 2,
                        "stdout": "Error: Missing required field: specFields",
                        "stderr": "",
                    }
                ],
                "warnings": [
                    "Requirement has missing or weakly inferred information: spec fields"
                ],
            },
        )

        self.assertEqual(analysis["status"], "failed")
        self.assertEqual(analysis["failedStep"], "spec_generator")
        self.assertEqual(
            analysis["primaryClassification"]["type"],
            "incomplete-requirement",
        )


if __name__ == "__main__":
    unittest.main()
