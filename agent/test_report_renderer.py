"""Tests for Markdown Agent report rendering."""

from __future__ import annotations

import unittest

from agent.report_renderer import render_log_analysis_report, render_requirement_report


class ReportRendererTest(unittest.TestCase):
    def test_requirement_report_keeps_safety_recovery_and_kind_evidence(self) -> None:
        report = render_requirement_report(
            {
                "requirementSummary": {"kind": "AppConfig", "managedResources": ["ConfigMap"]},
                "localLLM": {"model": "local"},
                "missingInformation": [],
                "retrievedKnowledge": [],
                "toolResults": [
                    {
                        "tool": "kind_deployment",
                        "status": "failed",
                        "exitCode": 1,
                        "command": ["kind"],
                        "deploymentSummary": {
                            "status": "failed",
                            "clusterName": "test",
                            "failedStep": "docker-info",
                            "validator": {"name": "appconfig-configmap"},
                        },
                    }
                ],
                "recovery": {
                    "waitingForUserApproval": True,
                    "plan": {
                        "classification": "docker-kind-connection",
                        "validatedRecoveryToolCalls": [
                            {"tool": "kind_deployment", "mode": "execute", "requiresApproval": True}
                        ],
                    },
                },
                "safetyEvaluation": {"recoveryApprovalGate": {"status": "waiting-for-user-approval"}},
                "selectedProfile": {},
                "generatedFiles": {},
                "warnings": [],
                "errors": ["kind failed"],
                "nextRecommendedActions": [],
            }
        )

        self.assertIn("appconfig-configmap", report)
        self.assertIn("docker-kind-connection", report)
        self.assertIn("Waiting for user approval", report)
        self.assertIn("Safety Evaluation", report)

    def test_log_analysis_report_contains_decision_and_tool(self) -> None:
        report = render_log_analysis_report(
            {
                "llmAnalysis": {"decision": "failed", "rootCause": "test"},
                "logAnalyzerResult": {"status": "succeeded", "exitCode": 0, "command": ["analyze"]},
                "retrievedKnowledge": [],
                "warnings": [],
            }
        )
        self.assertIn("Decision: `failed`", report)
        self.assertIn("log_analyzer", report)


if __name__ == "__main__":
    unittest.main()
