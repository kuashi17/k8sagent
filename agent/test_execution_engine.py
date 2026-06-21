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
