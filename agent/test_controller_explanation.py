"""Tests for beginner-facing Controller contract explanations."""

from __future__ import annotations

import unittest

from agent.controller_explanation import build_controller_explanation


class ControllerExplanationTest(unittest.TestCase):
    def test_network_policy_uses_plural_rbac_resource(self) -> None:
        result = build_controller_explanation(
            {
                "requirementSummary": {
                    "kind": "AppAccessPolicy",
                    "managedResources": ["NetworkPolicy"],
                    "resourcePolicies": [
                        {
                            "kind": "NetworkPolicy",
                            "strategy": "create-or-update",
                        }
                    ],
                }
            },
            [],
        )

        self.assertIn(
            "networking.k8s.io/networkpolicies",
            result["rbacReasons"][0],
        )


if __name__ == "__main__":
    unittest.main()
