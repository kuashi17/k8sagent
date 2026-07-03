from __future__ import annotations

import unittest

from agent.evaluation.local_llm_consistency_runner import (
    expected_failures,
    semantic_record,
)


class LocalLlmConsistencyRunnerTest(unittest.TestCase):
    def test_semantic_record_ignores_wording_and_paths(self) -> None:
        record = semantic_record(
            {
                "requirementSummary": {
                    "kind": "AppService",
                    "domain": "sample.io",
                    "group": "apps",
                    "version": "v1alpha1",
                    "managedResources": ["Deployment"],
                },
                "validatedToolCalls": [{"tool": "spec_generator", "reason": "variable prose"}],
                "finalLLM": {"output": {"executionDecision": "succeeded"}},
                "llmPlannerUsed": True,
            }
        )
        self.assertEqual(record["validatedTools"], ["spec_generator"])
        self.assertTrue(record["llmPlannerUsed"])

    def test_expected_contract_reports_semantic_difference(self) -> None:
        failures = expected_failures(
            {"managedResources": ["Service"]},
            {"managedResources": ["Deployment"]},
        )
        self.assertEqual(failures[0]["field"], "managedResources")


if __name__ == "__main__":
    unittest.main()
