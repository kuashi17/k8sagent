"""Tests for beginner-facing Agent result summaries."""

from __future__ import annotations

import unittest

from web.result_presenter import present_run_result


class ResultPresenterTest(unittest.TestCase):
    def test_dry_run_exposes_review_then_execute_action(self) -> None:
        result = present_run_result(
            {
                "state": "succeeded",
                "jobType": "requirement",
                "summary": {
                    "agentMode": "dry-run",
                    "requirementSummary": {
                        "kind": "WebService",
                        "managedResources": [
                            "Deployment",
                            "Service",
                        ],
                        "shortSummary": "Deployment와 Service를 관리합니다.",
                    },
                    "toolResults": [
                        {"tool": "spec_generator", "exitCode": 0}
                    ],
                    "generatedFiles": {
                        "operatorSpec": "generated/webservice.yaml"
                    },
                    "warnings": [],
                    "errors": [],
                    "nextRecommendedActions": ["계획을 검토합니다."],
                    "finalLLM": {"output": {}},
                },
            }
        )

        self.assertTrue(result.succeeded)
        self.assertTrue(result.can_execute)
        self.assertEqual(result.kind, "WebService")
        self.assertEqual(
            result.managed_resources,
            ["Deployment", "Service"],
        )


if __name__ == "__main__":
    unittest.main()
