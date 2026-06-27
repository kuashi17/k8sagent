"""Tests for the unified evaluation report."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.evaluation.unified_evaluation import (
    build_unified_evaluation,
    e2e_section,
    latency_section,
)


class UnifiedEvaluationTest(unittest.TestCase):
    def test_skipped_optional_idempotency_is_not_failed_evidence(self) -> None:
        result = e2e_section(
            {"results": []},
            {"status": "skipped", "reason": "context unavailable"},
            {
                "results": [
                    {
                        "status": "passed",
                        "profileUsed": False,
                        "deploymentSummary": {
                            "checks": {
                                "lifecycleIdempotency": {
                                    "reapplyStable": True
                                },
                                "lifecycleDelete": {
                                    "managedResources": {
                                        "configmap/sample": {
                                            "passed": True
                                        }
                                    }
                                },
                                "lifecycleRestore": {"restored": True},
                            }
                        },
                    }
                ]
            },
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["total"], 5)

    def test_expanded_full_matrix_uses_twenty_minute_budget(self) -> None:
        result = latency_section(
            {
                "current": {
                    "suite": "full",
                    "status": "passed",
                    "totalSeconds": 931.678,
                    "checks": {},
                }
            }
        )

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["targetSeconds"], 1200.0)

    def test_report_has_required_top_level_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "reliability").mkdir()
            (root / "profileless-compile").mkdir()
            (root / "profile-kind").mkdir()
            (root / "profileless-kind").mkdir()
            (root / "rag-quality.json").write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "metrics": {"hitAt3": 1.0},
                    }
                ),
                encoding="utf-8",
            )
            (root / "reliability" / "reliability-test-results.json").write_text(
                json.dumps(
                    {
                        "tests": [
                            {"name": "allowlist", "passed": True}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (
                root
                / "profileless-compile"
                / "profileless-compile-results.json"
            ).write_text(
                json.dumps(
                    {
                        "requirements": [
                            {
                                "passed": True,
                                "kind": "WebService",
                                "controllerQuality": {
                                    "status": "passed",
                                    "score": 100,
                                    "criteria": {
                                        "testsPassed": {"passed": True}
                                    },
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (
                root
                / "profile-kind"
                / "profile-kind-matrix.json"
            ).write_text(
                json.dumps(
                    {
                        "results": [
                            {
                                "status": "passed",
                                "deploymentSummary": {
                                    "checks": {
                                        "lifecycleIdempotency": {
                                            "reapplyStable": True
                                        },
                                        "lifecycleDelete": {
                                            "managedResources": {
                                                "job/sample": {
                                                    "passed": True
                                                }
                                            }
                                        },
                                        "lifecycleRestore": {
                                            "restored": True
                                        },
                                    }
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (
                root
                / "profileless-kind"
                / "profileless-kind-results.json"
            ).write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "profileUsed": False,
                        "results": [
                            {
                                "status": "passed",
                                "profileUsed": False,
                                "deploymentSummary": {
                                    "checks": {
                                        "lifecycleIdempotency": {
                                            "reapplyStable": True
                                        },
                                        "lifecycleUpdate": {
                                            "assertions": [
                                                {"passed": True}
                                            ]
                                        },
                                        "lifecycleDelete": {
                                            "managedResources": {
                                                "deployment/sample": {
                                                    "passed": True
                                                },
                                                "service/sample": {
                                                    "passed": True
                                                },
                                            }
                                        },
                                        "lifecycleRestore": {
                                            "restored": True
                                        },
                                    }
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            payload = build_unified_evaluation(root)

        self.assertEqual(
            set(payload),
            {
                "requirementUnderstanding",
                "ragQuality",
                "artifactQuality",
                "validationSuccess",
                "safetyReliability",
                "e2eSuccess",
                "latency",
                "overallScore",
            },
        )
        self.assertEqual(payload["ragQuality"]["score"], 100.0)
        self.assertEqual(payload["artifactQuality"]["score"], 100.0)
        self.assertEqual(payload["e2eSuccess"]["score"], 100.0)
        self.assertEqual(
            payload["e2eSuccess"]["profilelessKindRuns"],
            1,
        )
        self.assertEqual(payload["safetyReliability"]["score"], 100.0)


if __name__ == "__main__":
    unittest.main()
