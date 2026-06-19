"""Tests for Agent artifact persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.report_writer import write_agent_artifacts


class ReportWriterTest(unittest.TestCase):
    def test_writes_core_and_tool_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_agent_artifacts(
                root,
                {
                    "timings": {"totalSeconds": 1.0},
                    "evidenceTrace": {"ok": True},
                    "retrievalDetails": {},
                },
                {"llmInput": {"mode": "test"}, "llmOutput": {"toolCalls": []}, "rawOutput": "{}"},
                [],
                {
                    "validatedToolCalls": [],
                    "rejectedToolCalls": [],
                    "deferredToolCalls": [],
                    "toolResults": [
                        {
                            "tool": "validation",
                            "stdout": "ok",
                            "stderr": "",
                            "steps": [{"target": "test", "stdout": "passed", "stderr": ""}],
                        }
                    ],
                },
            )

            self.assertTrue((root / "summary.json").is_file())
            self.assertEqual(json.loads((root / "llm-input.json").read_text())["mode"], "test")
            self.assertEqual((root / "01-validation.stdout.log").read_text(), "ok")
            self.assertEqual((root / "01-validation-01-test.stdout.log").read_text(), "passed")

    def test_writes_recovery_checkpoint_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_agent_artifacts(
                root,
                {
                    "failureContext": {"failedTool": "kind_deployment"},
                    "recovery": {"plan": {"classification": "docker-kind-connection"}},
                },
                {},
                [],
                [],
            )

            plan = json.loads((root / "validated-recovery-plan.json").read_text())
            self.assertEqual(plan["classification"], "docker-kind-connection")
            self.assertTrue((root / "failure-context.json").is_file())


if __name__ == "__main__":
    unittest.main()
