"""Tests for the shared Agent/Web result contract."""

from __future__ import annotations

import unittest

from agent.contracts import AgentResult
from agent.result_builder import build_agent_result


class AgentResultBuilderTest(unittest.TestCase):
    def test_read_only_capability_explains_restricted_permissions(self) -> None:
        result = build_agent_result(
            {
                "agentMode": "dry-run",
                "requirementSummary": {
                    "kind": "DeploymentHealth",
                    "managedResources": [],
                    "observedResources": ["Deployment"],
                    "resourcePolicies": [
                        {
                            "kind": "Deployment",
                            "strategy": "read-only",
                            "ownership": "none",
                            "deletionPolicy": "retain",
                        }
                    ],
                },
                "generatedFiles": {},
                "toolResults": [],
                "finalLLM": {"output": {}},
                "warnings": [],
                "errors": [],
                "nextRecommendedActions": [],
                "recovery": {},
            }
        )

        details = result["technicalDetails"]
        self.assertEqual(details["observedResources"], ["Deployment"])
        self.assertEqual(
            details["capabilitySupport"][0]["accessMode"],
            "read-only",
        )
        self.assertIn(
            "get/list/watch",
            details["codeExplanation"]["rbacReasons"][0],
        )
        self.assertIn(
            "deletion=retain",
            details["codeExplanation"]["deletionBehavior"][0],
        )

    def test_builds_single_presentation_contract(self) -> None:
        result = build_agent_result(
            {
                "agentMode": "execute",
                "requirementSummary": {
                    "kind": "Example",
                    "managedResources": ["Deployment"],
                },
                "generatedFiles": {"operatorSpec": "generated/example.yaml"},
                "toolResults": [
                    {"tool": "validation", "exitCode": 0}
                ],
                "finalLLM": {
                    "output": {
                        "beginnerSummary": "완료했습니다.",
                        "validationResults": {"makeTest": "succeeded"},
                    }
                },
                "warnings": [],
                "errors": [],
                "nextRecommendedActions": ["결과 확인"],
                "recovery": {},
            }
        )

        validated = AgentResult.model_validate(result)
        self.assertEqual(validated.status, "succeeded")
        self.assertEqual(validated.technicalDetails.kind, "Example")
        self.assertEqual(validated.validationResults["makeTest"], "succeeded")
        support = validated.technicalDetails.capabilitySupport[0]
        self.assertIn("lastValidatedAt", support)
        explanation = validated.technicalDetails.codeExplanation
        self.assertTrue(explanation["watches"])
        self.assertTrue(explanation["rbacReasons"])
        self.assertTrue(explanation["deletionBehavior"])
        self.assertTrue(explanation["firstFiles"])

    def test_capability_and_recovery_require_approval(self) -> None:
        result = build_agent_result(
            {
                "agentMode": "dry-run",
                "requirementSummary": {},
                "generatedFiles": {
                    "capabilityProposal": "generated/capability.yaml"
                },
                "toolResults": [],
                "finalLLM": {"output": {}},
                "warnings": [],
                "errors": [],
                "nextRecommendedActions": [],
                "recovery": {"waitingForUserApproval": True},
            }
        )

        self.assertEqual(result["status"], "recovery-awaiting-approval")
        self.assertEqual(
            [item["type"] for item in result["approvalRequests"]],
            ["capability", "recovery"],
        )
        self.assertFalse(result["canExecute"])


if __name__ == "__main__":
    unittest.main()
