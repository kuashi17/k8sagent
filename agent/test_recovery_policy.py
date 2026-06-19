"""Tests for deterministic and approval-gated recovery policy."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from agent.recovery_policy import (
    deterministic_recovery_classification,
    validate_recovery_plan,
)


class RecoveryPolicyTest(unittest.TestCase):
    def test_docker_failure_is_deterministic(self) -> None:
        classification = deterministic_recovery_classification(
            {
                "failedTool": "kind_deployment",
                "failedStep": "docker-info",
                "stderrTail": "Cannot connect to the Docker daemon.",
            }
        )
        self.assertEqual(classification, "docker-kind-connection")

    def test_unknown_recovery_tool_is_rejected_and_never_auto_runs(self) -> None:
        policy = validate_recovery_plan(
            {
                "classification": "rbac-forbidden",
                "rootCause": "forbidden",
                "recoveryToolCalls": [{"tool": "kubectl", "mode": "execute"}],
            },
            {"failedTool": "validation", "failedStep": "make test", "stderrTail": "forbidden"},
            {"generatedFiles": {"operatorSpec": "missing.yaml"}},
        )
        plan = policy["validatedRecoveryPlan"]
        self.assertEqual(plan["status"], "waiting-for-user-approval")
        self.assertTrue(all(item["requiresApproval"] for item in plan["validatedRecoveryToolCalls"]))
        self.assertEqual(policy["rejectedRecoveryToolCalls"][0]["tool"], "kubectl")

    def test_invalid_field_type_starts_with_requirement_correction(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            spec = Path(temp) / "spec.yaml"
            spec.write_text(
                yaml.safe_dump(
                    {
                        "specFields": [{"name": "broken", "type": "notatype"}],
                        "statusFields": [],
                    }
                ),
                encoding="utf-8",
            )
            policy = validate_recovery_plan(
                {},
                {"failedTool": "validation", "failedStep": "make generate"},
                {"generatedFiles": {"operatorSpec": str(spec)}},
            )
        calls = policy["validatedRecoveryPlan"]["validatedRecoveryToolCalls"]
        self.assertEqual(calls[0]["tool"], "requirement_editor")
        self.assertEqual(policy["validatedRecoveryPlan"]["classification"], "invalid-field-type")


if __name__ == "__main__":
    unittest.main()
