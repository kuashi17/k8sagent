"""Tests for structured Agent data contracts."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from agent.contracts import (
    AgentSummary,
    ExecutionResult,
    FailureContext,
    FinalEvaluation,
    RecoveryPlan,
    RequirementPlan,
    ToolResult,
)


class ContractTest(unittest.TestCase):
    def test_requirement_plan_requires_tool_calls(self) -> None:
        with self.assertRaises(ValidationError):
            RequirementPlan.model_validate(
                {
                    "requirementSummary": "Create an Operator.",
                    "missingInformation": [],
                    "recommendedProfile": "",
                    "plannedSteps": [],
                    "toolCalls": [],
                    "risks": [],
                    "nextActions": [],
                }
            )

    def test_requirement_plan_rejects_tool_call_without_mode(self) -> None:
        with self.assertRaises(ValidationError):
            RequirementPlan.model_validate(
                {
                    "requirementSummary": "Create an Operator.",
                    "missingInformation": [],
                    "recommendedProfile": "",
                    "plannedSteps": [],
                    "toolCalls": [{"tool": "spec_generator"}],
                    "risks": [],
                    "nextActions": [],
                }
            )

    def test_tool_result_preserves_extension_fields(self) -> None:
        result = ToolResult.model_validate(
            {
                "tool": "validation",
                "command": ["make", "test"],
                "exitCode": 0,
                "status": "succeeded",
                "customEvidence": {"tests": 3},
            }
        ).to_dict()
        self.assertEqual(result["customEvidence"], {"tests": 3})

    def test_requested_contracts_generate_json_schema(self) -> None:
        for contract in (
            RequirementPlan,
            ToolResult,
            ExecutionResult,
            FinalEvaluation,
            FailureContext,
            RecoveryPlan,
            AgentSummary,
        ):
            schema = contract.model_json_schema()
            self.assertEqual(schema["type"], "object")

    def test_execution_result_rejects_negative_timings(self) -> None:
        with self.assertRaises(ValidationError):
            ExecutionResult.model_validate(
                {
                    "validatedToolCalls": [],
                    "rejectedToolCalls": [],
                    "deferredToolCalls": [],
                    "toolResults": [],
                    "timings": {
                        "toolValidationSeconds": -1.0,
                        "toolExecutionSeconds": 0.0,
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
