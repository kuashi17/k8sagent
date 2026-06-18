"""Focused tests for small local-model requirement planning output."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from agent.llm.client import LLMConfig
from agent.llm.planner import normalize_requirement_plan, plan_requirement_with_llm


class RequirementPlanStabilityTest(unittest.TestCase):
    def test_normalizer_fills_non_executable_optional_arrays(self) -> None:
        output = normalize_requirement_plan(
            {
                "requirementSummary": "Create a WebService Operator.",
                "toolCalls": [{"tool": "spec_generator", "mode": "generate", "reason": "Generate spec."}],
            },
            {"path": ""},
        )

        self.assertEqual(output["missingInformation"], [])
        self.assertEqual(output["plannedSteps"], [])
        self.assertEqual(output["risks"], [])
        self.assertEqual(output["nextActions"], [])
        self.assertEqual(output["recommendedProfile"], "")

    def test_missing_tool_calls_triggers_one_schema_repair(self) -> None:
        incomplete = json.dumps(
            {
                "requirementSummary": "Create a WebService Operator.",
                "missingInformation": [],
                "recommendedProfile": "",
                "plannedSteps": [],
                "risks": [],
                "nextActions": [],
            }
        )
        repaired = json.dumps(
            {
                "requirementSummary": "Create a WebService Operator.",
                "toolCalls": [{"tool": "spec_generator", "mode": "generate", "reason": "Generate spec."}],
                "missingInformation": [],
                "recommendedProfile": "",
                "plannedSteps": ["Generate the spec."],
                "risks": [],
                "nextActions": [],
            }
        )

        with patch("agent.llm.planner.chat_json", side_effect=[incomplete, repaired]) as mocked:
            output, llm_input, raw = plan_requirement_with_llm(
                "Create a WebService Operator.",
                [],
                {},
                "dry-run",
                config=LLMConfig(max_tokens=700),
            )

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(output["toolCalls"][0]["tool"], "spec_generator")
        self.assertTrue(llm_input["responseRepair"]["attempted"])
        self.assertEqual(raw, repaired)


if __name__ == "__main__":
    unittest.main()
