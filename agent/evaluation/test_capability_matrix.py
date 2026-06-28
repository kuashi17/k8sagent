"""Tests for evidence-derived capability support levels."""

from __future__ import annotations

import unittest

from agent.evaluation.capability_matrix import build_capability_matrix


class CapabilityMatrixTest(unittest.TestCase):
    def test_stable_requires_drift_and_full_runtime_evidence(self) -> None:
        compile_results = {
            "requirements": [
                {
                    "requirement": "requirements/example.txt",
                    "managedResources": ["Deployment", "Service"],
                    "passed": True,
                }
            ]
        }
        evidence = {
            name: {"status": "passed"}
            for name in (
                "idempotency",
                "driftRecovery",
                "rbacLeastPrivilege",
                "deletionPolicy",
                "stateMachine",
            )
        }
        result = build_capability_matrix(
            compile_results,
            {
                "results": [
                    {
                        "requirement": "requirements/example.txt",
                        "status": "passed",
                        "deploymentSummary": {
                            "runtimeEvidence": evidence
                        },
                    }
                ]
            },
        )
        levels = {
            item["resource"]: item["level"]
            for item in result["capabilities"]
        }
        self.assertEqual(levels["Deployment"], "stable")
        self.assertEqual(levels["Service"], "stable")
        self.assertEqual(levels["ClusterRole"], "experimental")
