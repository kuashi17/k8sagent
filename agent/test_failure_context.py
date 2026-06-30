"""Tests for recovery failure context construction."""

from __future__ import annotations

import unittest

from agent.failure_context import detect_failure_context


class FailureContextTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = {
            "workspace": "workspace/generated-operators",
            "targetProjectDir": "workspace/generated-operators/widget-operator",
            "requirementSummary": {
                "kind": "Widget",
                "group": "apps.example.io",
                "version": "v1alpha1",
            },
            "generatedFiles": {
                "operatorSpec": "generated/widget-operator-spec.yaml",
                "commandPlan": "generated/widget-command-plan.md",
            },
        }

    def test_rejected_tool_call_becomes_validation_failure(self) -> None:
        failure = detect_failure_context(
            self.context,
            {
                "rejectedToolCalls": [{"tool": "shell", "reason": "not allowed"}],
                "toolResults": [],
            },
            "dry-run",
        )

        self.assertEqual(failure["failedTool"], "tool-validation")
        self.assertIn("not allowed", failure["stderrTail"])

    def test_failed_validation_reports_make_target_and_prior_steps(self) -> None:
        failure = detect_failure_context(
            self.context,
            {
                "rejectedToolCalls": [],
                "toolResults": [
                    {"tool": "artifact_patcher", "exitCode": 0},
                    {
                        "tool": "validation",
                        "exitCode": 1,
                        "steps": [{"target": "test", "exitCode": 1}],
                        "stdout": "line 1\nline 2",
                        "stderr": "test failed",
                    },
                ],
            },
            "execute",
        )

        self.assertEqual(failure["failedStep"], "make test")
        self.assertEqual(failure["previousSuccessfulSteps"], ["artifact_patcher"])
        self.assertEqual(failure["agentMode"], "execute")

    def test_structured_tool_error_is_preserved_for_recovery(self) -> None:
        failure = detect_failure_context(
            self.context,
            {
                "rejectedToolCalls": [],
                "toolResults": [
                    {
                        "tool": "kind_deployment",
                        "exitCode": 1,
                        "errorCode": "RBAC_FORBIDDEN",
                        "errorDetails": {
                            "errorCode": "RBAC_FORBIDDEN",
                            "category": "policy",
                            "message": "forbidden",
                            "stage": "rbac-preflight",
                            "resource": "deployments",
                            "verb": "patch",
                            "retryable": False,
                        },
                    }
                ],
            },
            "execute",
        )

        self.assertEqual(failure["errorCode"], "RBAC_FORBIDDEN")
        self.assertEqual(failure["errorDetails"]["resource"], "deployments")

    def test_dry_run_does_not_fail_only_for_missing_artifacts(self) -> None:
        failure = detect_failure_context(
            self.context,
            {"rejectedToolCalls": [], "toolResults": []},
            "dry-run",
        )

        self.assertIsNone(failure)


if __name__ == "__main__":
    unittest.main()
