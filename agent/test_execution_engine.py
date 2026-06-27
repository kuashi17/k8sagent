"""Tests for Agent Tool capability construction and execution ordering."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.execution_engine import (
    apply_resume_policy,
    build_supported_calls,
    execute_planned_tools,
    order_validated_tool_calls,
    execution_result,
)


def context(target: str = "workspace/generated-operators/example") -> dict:
    return {
        "requirement": "requirements/appconfig.txt",
        "workspace": "workspace/generated-operators",
        "targetProjectDir": target,
        "generatedFiles": {
            "operatorSpec": "generated/appconfig-operator-spec.yaml",
            "commandPlan": "generated/appconfig-command-plan.md",
        },
        "requirementSummary": {"managedResources": ["ConfigMap"]},
        "selectedProfile": {"path": "profiles/appconfig.yaml"},
        "kindDeploymentRequested": False,
        "resumeExisting": False,
    }


class ExecutionEngineTest(unittest.TestCase):
    def test_execution_result_is_validated_at_boundary(self) -> None:
        result = execution_result([], [], [], [], 0.1, 0.2)

        self.assertEqual(
            result["timings"],
            {
                "toolValidationSeconds": 0.1,
                "toolExecutionSeconds": 0.2,
            },
        )

    def test_tool_order_is_deterministic(self) -> None:
        calls = [
            {"tool": "validation"},
            {"tool": "spec_generator"},
            {"tool": "artifact_patcher"},
        ]
        self.assertEqual(
            [item["tool"] for item in order_validated_tool_calls(calls)],
            ["spec_generator", "artifact_patcher", "validation"],
        )

    def test_resume_policy_defers_only_scaffold(self) -> None:
        with tempfile.TemporaryDirectory(dir=".") as temp:
            ctx = context(str(Path(temp)))
            ctx["resumeExisting"] = True
            remaining, deferred = apply_resume_policy(
                [{"tool": "scaffold_runner"}, {"tool": "validation"}],
                ctx,
            )
        self.assertEqual([item["tool"] for item in remaining], ["validation"])
        self.assertEqual(deferred[0]["tool"], "scaffold_runner")

    def test_kind_capability_is_added_only_when_requested(self) -> None:
        ctx = context()
        ctx["selectedProfile"]["kindDeployment"] = {
            "enabled": True,
            "validator": "appconfig-configmap",
        }
        self.assertNotIn("kind_deployment", build_supported_calls(ctx, "dry-run", False))
        ctx["kindDeploymentRequested"] = True
        self.assertIn("kind_deployment", build_supported_calls(ctx, "dry-run", False))

    def test_known_capability_never_uses_proposal_approval(self) -> None:
        dry_run = build_supported_calls(context(), "dry-run", False)
        execute = build_supported_calls(context(), "execute", True)

        self.assertFalse(
            dry_run["capability_drafter"]["arguments"]["approve"]
        )
        self.assertFalse(
            execute["capability_drafter"]["arguments"]["approve"]
        )

    def test_unknown_capability_requires_matching_separate_approval(self) -> None:
        ctx = context()
        ctx["requirementSummary"] = {
            "managedResources": ["QuantumQueue"]
        }
        without_approval = build_supported_calls(ctx, "execute", True)
        self.assertFalse(
            without_approval["capability_drafter"]["arguments"]["approve"]
        )
        self.assertFalse(
            without_approval["scaffold_runner"]["arguments"]["execute"]
        )

        ctx["capabilityApproval"] = {
            "proposal": "generated/quantum-queue-capability-proposal.yaml",
            "proposalId": "reviewed-digest",
        }
        approved = build_supported_calls(ctx, "execute", True)
        self.assertTrue(
            approved["capability_drafter"]["arguments"]["approve"]
        )
        self.assertTrue(
            approved["scaffold_runner"]["arguments"]["execute"]
        )

    @patch("agent.execution_engine.tools.scaffold_runner")
    def test_unapproved_unknown_capability_forces_mutations_to_dry_run(
        self,
        scaffold_runner,
    ) -> None:
        scaffold_runner.return_value = {
            "exitCode": 0,
            "status": "succeeded",
            "stdout": "",
            "stderr": "",
        }
        ctx = context()
        ctx["requirementSummary"] = {
            "managedResources": ["QuantumQueue"]
        }
        result = execute_planned_tools(
            ctx,
            "execute",
            True,
            {
                "llmOutput": {
                    "toolCalls": [
                        {
                            "tool": "scaffold_runner",
                            "mode": "execute",
                        }
                    ]
                }
            },
        )

        self.assertEqual(
            result["validatedToolCalls"][0]["effectiveMode"],
            "dry-run",
        )
        self.assertFalse(
            result["validatedToolCalls"][0]["executeAllowed"]
        )
        self.assertEqual(
            result["deferredToolCalls"][0]["tool"],
            "capability_approval",
        )
        scaffold_runner.assert_called_once_with(
            "generated/appconfig-operator-spec.yaml",
            "workspace/generated-operators",
            execute=False,
        )

    @patch("agent.execution_engine.tools.scaffold_runner")
    @patch("agent.execution_engine.tools.capability_drafter")
    def test_runtime_pending_proposal_stops_execute_pipeline(
        self,
        capability_drafter,
        scaffold_runner,
    ) -> None:
        capability_drafter.return_value = {
            "exitCode": 0,
            "status": "succeeded",
            "stdout": '{"status":"pending-approval"}\n',
            "stderr": "",
        }
        ctx = context()
        result = execute_planned_tools(
            ctx,
            "execute",
            True,
            {
                "llmOutput": {
                    "toolCalls": [
                        {
                            "tool": "capability_drafter",
                            "mode": "execute",
                        },
                        {
                            "tool": "scaffold_runner",
                            "mode": "execute",
                        },
                    ]
                }
            },
        )

        self.assertTrue(ctx["capabilityApprovalBlocked"])
        self.assertEqual(
            [item["tool"] for item in result["toolResults"]],
            ["capability_drafter"],
        )
        self.assertEqual(
            result["deferredToolCalls"][0]["tool"],
            "scaffold_runner",
        )
        scaffold_runner.assert_not_called()

    @patch("agent.execution_engine.tools.command_planner")
    @patch("agent.execution_engine.tools.spec_generator")
    def test_execution_stops_after_first_failure(self, spec_generator, command_planner) -> None:
        spec_generator.return_value = {"exitCode": 1, "status": "failed", "stdout": "", "stderr": "failed"}
        command_planner.return_value = {"exitCode": 0, "status": "succeeded", "stdout": "", "stderr": ""}
        planner = {
            "llmOutput": {
                "toolCalls": [
                    {"tool": "spec_generator", "mode": "generate"},
                    {"tool": "command_planner", "mode": "dry-run"},
                ]
            }
        }

        result = execute_planned_tools(context(), "dry-run", False, planner)

        self.assertEqual([item["tool"] for item in result["toolResults"]], ["spec_generator"])
        command_planner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
