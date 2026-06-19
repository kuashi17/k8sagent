"""Tests for requirement run summary assembly."""

from __future__ import annotations

import argparse
import unittest

from agent.summary_builder import build_requirement_summary


class SummaryBuilderTest(unittest.TestCase):
    def test_failure_summary_keeps_recovery_and_removes_internal_wait_error(self) -> None:
        args = argparse.Namespace(
            profile="",
            mode="execute",
            run_level="standard",
            skip_final_llm_evaluation=False,
            execute=True,
            kind_deploy=True,
            resume_existing=True,
        )
        summary = build_requirement_summary(
            args,
            {
                "requirement": "requirements/appconfig.txt",
                "requirementSummary": {"kind": "AppConfig"},
                "intentAnalysis": {},
                "missingInformation": [],
                "retrievedKnowledge": [],
                "retrievalDetails": {},
                "selectedProfile": {},
                "profileCandidates": [],
                "generatedFiles": {
                    "operatorSpec": "generated/spec.yaml",
                    "commandPlan": "generated/plan.md",
                },
                "workspace": "workspace/generated-operators",
            },
            {
                "llmPlannerUsed": True,
                "localLLM": {},
                "error": "",
                "llmOutput": {"toolCalls": [{"tool": "kind_deployment"}]},
            },
            {
                "validatedToolCalls": [{"tool": "kind_deployment"}],
                "rejectedToolCalls": [],
                "deferredToolCalls": [],
                "toolResults": [
                    {
                        "tool": "kind_deployment",
                        "exitCode": 1,
                        "status": "failed",
                        "stdout": "",
                    }
                ],
            },
            {
                "llmPlannerUsed": False,
                "localLLM": {},
                "error": "Execution failed; recovery plan generated and waiting for user approval.",
                "llmOutput": {},
            },
            {
                "llmOutput": {"classification": "docker-kind-connection"},
                "policyEvaluation": {},
            },
            {"failedTool": "kind_deployment"},
        )
        self.assertTrue(summary["recovery"]["waitingForUserApproval"])
        self.assertEqual(
            summary["recovery"]["plan"]["classification"],
            "docker-kind-connection",
        )
        self.assertEqual(
            summary["errors"],
            ["kind_deployment failed with exit code 1"],
        )


if __name__ == "__main__":
    unittest.main()
