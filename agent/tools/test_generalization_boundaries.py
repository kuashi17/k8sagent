"""Regression guards for generalized generation boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.tools.controller_renderer import render_controller


REPO_ROOT = Path(__file__).resolve().parents[2]


class GeneralizationBoundaryTest(unittest.TestCase):
    def test_renderer_contains_no_resource_specific_dispatch(self) -> None:
        source = (
            REPO_ROOT
            / "agent"
            / "tools"
            / "controller_renderer.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            '"ConfigMap"',
            '"Secret"',
            '"PersistentVolumeClaim"',
            '"CronJob"',
            '"Deployment"',
            '"StatefulSet"',
            '"Service"',
            '"Namespace"',
            "resource.kind ==",
            "resource.kind !=",
        )
        for value in forbidden:
            self.assertNotIn(value, source)

    def test_matrix_cases_live_in_fixture_not_runner(self) -> None:
        runner = (
            REPO_ROOT
            / "agent"
            / "evaluation"
            / "profileless_kind_runner.py"
        ).read_text(encoding="utf-8")
        for value in (
            "WebService",
            "SecretSync",
            "ScheduledTask",
            "NamespaceLabelPolicy",
        ):
            self.assertNotIn(value, runner)

    def test_unseen_custom_kind_uses_existing_capabilities(
        self,
    ) -> None:
        rendered = render_controller(
            {
                "project": {
                    "module": "sample.io/queue-worker-operator"
                },
                "api": {
                    "kind": "QueueWorker",
                    "group": "workloads",
                    "version": "v1alpha1",
                },
                "controller": {
                    "managedResources": [
                        "Deployment",
                        "Service",
                    ]
                },
                "specFields": [
                    {"name": "image"},
                    {"name": "replicas"},
                    {"name": "port"},
                ],
                "statusFields": [{"name": "phase"}],
                "rbacResources": [],
            }
        )

        self.assertIn("type QueueWorkerReconciler", rendered)
        self.assertIn("reconcileDeployment", rendered)
        self.assertIn("reconcileService", rendered)


if __name__ == "__main__":
    unittest.main()
