"""Tests for profile-less kind contract generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.evaluation.profileless_kind_runner import (
    build_kind_command,
    build_kind_contract,
)


class ProfilelessKindRunnerTest(unittest.TestCase):
    def test_webservice_contract_uses_generated_behavior(self) -> None:
        spec = {
            "project": {
                "name": "web-service-operator",
                "domain": "sample.io",
                "module": "sample.io/web-service-operator",
            },
            "api": {
                "kind": "WebService",
                "plural": "webservices",
                "version": "v1alpha1",
                "group": "apps",
                "domain": "sample.io",
            },
            "specFields": [
                {"name": "appName", "type": "string"},
                {"name": "replicas", "type": "int32"},
            ],
            "statusFields": [{"name": "phase", "type": "string"}],
            "controller": {
                "managedResources": ["Deployment", "Service"],
            },
            "rbac": {"resources": []},
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "web-service-operator"
            sample = (
                project
                / "config"
                / "samples"
                / "apps_v1alpha1_webservice.yaml"
            )
            sample.parent.mkdir(parents=True, exist_ok=True)
            sample.write_text(
                """
apiVersion: apps.sample.io/v1alpha1
kind: WebService
metadata:
  name: webservice-sample
spec:
  appName: sample-app-name
  replicas: 1
""",
                encoding="utf-8",
            )
            contract = build_kind_contract(
                spec,
                project,
                "profileless-test",
            )
            config = contract["validatorConfig"]

            self.assertFalse(config.get("profileUsed", False))
            self.assertEqual(config["updateSpec"], {"replicas": 2})
            self.assertEqual(
                [
                    item["resource"]
                    for item in config["managedResources"]
                ],
                ["deployment", "service"],
            )
            self.assertEqual(
                {
                    item["name"]
                    for item in config["managedResources"]
                },
                {"sample-app-name"},
            )
            command = build_kind_command(contract)
            self.assertIn("--skip-prepare-controller", command)
            self.assertIn("--skip-prevalidation", command)


if __name__ == "__main__":
    unittest.main()
