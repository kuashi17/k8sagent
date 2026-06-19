"""Tests for compact final LLM evaluation."""

from __future__ import annotations

import unittest

from agent.final_evaluator import compact_final_input


class FinalEvaluatorTest(unittest.TestCase):
    def test_final_input_omits_full_plan_payload(self) -> None:
        result = compact_final_input(
            {
                "requirementSummary": {"kind": "Widget"},
                "generatedFiles": {"operatorSpec": "generated/widget.yaml"},
            },
            {"plannedSteps": ["one", "two"], "toolCalls": [{"tool": "large"}]},
            {
                "validatedToolCalls": [
                    {
                        "tool": "validation",
                        "effectiveMode": "execute",
                        "reason": "long reason",
                    }
                ],
                "rejectedToolCalls": [],
                "deferredToolCalls": [],
                "toolResults": [],
            },
            [],
            [],
        )

        self.assertNotIn("plannedSteps", result)
        self.assertNotIn("toolCalls", result)
        self.assertEqual(result["plannedStepCount"], 2)
        self.assertEqual(
            result["validatedToolCalls"],
            [{"tool": "validation", "effectiveMode": "execute"}],
        )
