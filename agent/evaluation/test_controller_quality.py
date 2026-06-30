"""Tests for generated Controller quality scoring."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.evaluation.controller_quality import (
    collect_behavior_evidence,
    evaluate_controller_quality,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class ControllerQualityTest(unittest.TestCase):
    @unittest.skipUnless(
        (
            REPO_ROOT
            / "workspace"
            / "generated-operators"
            / "app-config-operator"
        ).is_dir(),
        "local generated AppConfig fixture is not tracked in CI",
    )
    def test_existing_appconfig_fixture_meets_quality_contract(self) -> None:
        result = evaluate_controller_quality(
            REPO_ROOT
            / "workspace"
            / "generated-operators"
            / "app-config-operator",
            REPO_ROOT / "generated" / "appconfig-operator-spec.yaml",
            [
                {
                    "tool": "validation",
                    "steps": [{"target": "test", "exitCode": 0}],
                }
            ],
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["score"], 100.0)

    def test_missing_project_is_reported_as_not_run(self) -> None:
        result = evaluate_controller_quality(
            REPO_ROOT / "workspace" / "generated-operators" / "missing",
            REPO_ROOT / "generated" / "missing.yaml",
        )
        self.assertEqual(result["status"], "not-run")
        self.assertEqual(result["score"], 0)

    def test_behavior_evidence_tracks_watch_and_status_assignments(self) -> None:
        evidence = collect_behavior_evidence(
            """
            builder.Owns(managedObject("apps", "v1", "Deployment", "", ""))
            instance.Status.ReadyReplicas = value
            """,
            {
                "controller": {
                    "managedResources": ["Deployment", "Service"]
                },
                "statusFields": [
                    {"name": "readyReplicas"},
                    {"name": "message"},
                ],
            },
        )

        self.assertEqual(
            evidence["watchRegistrations"],
            ["Deployment"],
        )
        self.assertEqual(
            evidence["assignedStatusFields"],
            ["readyReplicas"],
        )

    def test_behavior_evidence_accepts_multiline_method_chain(self) -> None:
        evidence = collect_behavior_evidence(
            """
            ctrl.NewControllerManagedBy(mgr).
                For(&appsv1.Example{}).
                Owns(managedObject("apps", "v1", "Deployment", "", "")).
                Complete(r)
            """,
            {
                "controller": {
                    "managedResources": ["Deployment"]
                },
                "statusFields": [],
            },
        )

        self.assertEqual(
            evidence["watchRegistrations"],
            ["Deployment"],
        )

    def test_behavior_evidence_tracks_external_read_only_watch(self) -> None:
        evidence = collect_behavior_evidence(
            """
            builder.Watches(
                managedObject("apps", "v1", "Deployment", "", ""),
                handler.EnqueueRequestsFromMapFunc(r.mapDeployment),
            )
            """,
            {
                "controller": {
                    "managedResources": [],
                    "observedResources": ["Deployment"],
                },
                "statusFields": [],
            },
        )

        self.assertEqual(evidence["watchRegistrations"], ["Deployment"])


if __name__ == "__main__":
    unittest.main()
