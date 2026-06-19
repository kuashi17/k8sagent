"""Tests for safety and evidence trace assembly."""

from __future__ import annotations

import argparse
import unittest

from agent.evidence_builder import (
    build_requirement_evidence_trace,
    build_requirement_safety_evaluation,
)


class EvidenceBuilderTest(unittest.TestCase):
    def test_safety_records_forced_dry_run_and_recovery_gate(self) -> None:
        args = argparse.Namespace(mode="dry-run", execute=False)
        safety = build_requirement_safety_evaluation(
            args,
            {
                "workspace": "workspace/generated-operators",
                "targetProjectDir": "workspace/generated-operators/example",
            },
            {
                "validatedToolCalls": [
                    {
                        "tool": "scaffold_runner",
                        "effectiveMode": "dry-run",
                        "mutating": True,
                        "executeAllowed": False,
                    }
                ],
                "rejectedToolCalls": [],
                "deferredToolCalls": [],
            },
            {"llmPlannerUsed": True, "localLLM": {"model": "local"}},
            {"failedTool": "validation"},
        )
        self.assertEqual(safety["executionModeGate"]["forcedDryRunTools"], ["scaffold_runner"])
        self.assertEqual(safety["recoveryApprovalGate"]["status"], "waiting-for-user-approval")

    def test_evidence_trace_connects_rag_tools_and_recovery(self) -> None:
        trace = build_requirement_evidence_trace(
            {
                "retrievalDetails": {
                    "retrievalMode": "hybrid",
                    "selectedContext": [{"path": "guide.md", "title": "Guide"}],
                },
                "ragEvidence": [],
                "toolResults": [
                    {
                        "tool": "validation",
                        "status": "failed",
                        "exitCode": 1,
                        "stderr": "boom",
                    }
                ],
                "recovery": {
                    "waitingForUserApproval": True,
                    "plan": {"validatedRecoveryToolCalls": [{"tool": "validation"}]},
                },
            }
        )
        self.assertEqual(trace["ragEvidence"]["selectedDocuments"][0]["path"], "guide.md")
        self.assertEqual(trace["executionEvidence"][0]["tool"], "validation")
        self.assertTrue(trace["recoveryEvidence"]["waitingForUserApproval"])


if __name__ == "__main__":
    unittest.main()
