"""Tests for evidence-derived capability support levels."""

from __future__ import annotations

import unittest

from agent.evaluation.capability_matrix import build_capability_matrix


class CapabilityMatrixTest(unittest.TestCase):
    def test_failed_kind_matrix_is_not_capability_evidence(self) -> None:
        result = build_capability_matrix(
            {"status": "passed", "requirements": []},
            {
                "status": "failed",
                "results": [
                    {
                        "status": "failed",
                        "deploymentSummary": {
                            "runtimeEvidence": {
                                "idempotency": {"status": "not-run"}
                            }
                        },
                    }
                ],
            },
        )

        self.assertEqual(result["status"], "not-evaluated")
        self.assertFalse(result["promotionEligible"])
        self.assertEqual(result["capabilities"], [])
        self.assertEqual(
            result["counts"],
            {"stable": 0, "beta": 0, "experimental": 0},
        )

    def test_failed_kind_run_is_not_recorded_as_capability_evidence(self) -> None:
        result = build_capability_matrix(
            {
                "requirements": [
                    {
                        "requirement": "requirements/policy.txt",
                        "managedResources": ["NetworkPolicy"],
                        "passed": True,
                    }
                ]
            },
            {
                "results": [
                    {
                        "requirement": "requirements/policy.txt",
                        "status": "failed",
                        "deploymentSummary": {
                            "failedStep": "docker-info",
                            "runtimeEvidence": {
                                "idempotency": {"status": "not-run"}
                            },
                        },
                    }
                ]
            },
        )

        policy = next(
            item
            for item in result["capabilities"]
            if item["resource"] == "NetworkPolicy"
        )
        self.assertEqual(policy["level"], "experimental")
        self.assertEqual(policy["evidence"], [])
        self.assertEqual(
            policy["limitations"],
            ["No kind lifecycle evidence is recorded."],
        )

    def test_catalog_alias_is_merged_into_canonical_resource(self) -> None:
        result = build_capability_matrix(
            {
                "requirements": [
                    {
                        "requirement": "requirements/pvc.txt",
                        "managedResources": ["PVC"],
                        "passed": True,
                    }
                ]
            },
            {
                "results": [
                    {
                        "requirement": "requirements/pvc.txt",
                        "status": "passed",
                        "deploymentSummary": {"runtimeEvidence": {}},
                    }
                ]
            },
        )
        resources = [item["resource"] for item in result["capabilities"]]
        self.assertIn("PersistentVolumeClaim", resources)
        self.assertNotIn("PVC", resources)

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
        deployment = next(
            item
            for item in result["capabilities"]
            if item["resource"] == "Deployment"
        )
        self.assertTrue(deployment["evidenceBased"])
        self.assertTrue(deployment["lastValidatedAt"])
