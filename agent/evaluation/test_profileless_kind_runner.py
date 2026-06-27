"""Tests for profile-less kind contract generation."""

from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from agent.evaluation.profileless_kind_runner import (
    build_kind_command,
    build_kind_contract,
    project_content_digest,
    load_precompiled_results,
)


class ProfilelessKindRunnerTest(unittest.TestCase):
    def test_precompiled_results_require_existing_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "widget-operator"
            project.mkdir()
            result = root / "results.json"
            result.write_text(
                json.dumps(
                    {
                        "status": "passed",
                        "requirements": [
                            {
                                "requirement": "requirements/widget.txt",
                                "projectDir": str(project),
                                "passed": True,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            loaded = load_precompiled_results(result)

        self.assertIn("requirements/widget.txt", loaded)

    def test_access_bundle_contract_includes_cluster_role_finalizer(
        self,
    ) -> None:
        spec = {
            "project": {
                "name": "access-bundle-operator",
                "domain": "sample.io",
                "module": "sample.io/access-bundle-operator",
            },
            "api": {
                "kind": "AccessBundle",
                "plural": "accessbundles",
                "version": "v1alpha1",
                "group": "access",
                "domain": "sample.io",
            },
            "specFields": [
                {"name": "clusterRoleName", "type": "string"},
                {"name": "ruleVerbs", "type": "[]string"},
            ],
            "statusFields": [{"name": "phase", "type": "string"}],
            "controller": {"managedResources": ["ClusterRole"]},
            "rbac": {"resources": []},
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "access-bundle-operator"
            sample = (
                project
                / "config"
                / "samples"
                / "access_v1alpha1_accessbundle.yaml"
            )
            sample.parent.mkdir(parents=True, exist_ok=True)
            sample.write_text(
                """
apiVersion: access.sample.io/v1alpha1
kind: AccessBundle
metadata:
  name: access-bundle-sample
spec:
  clusterRoleName: managed-access
  ruleVerbs: [get]
""",
                encoding="utf-8",
            )

            config = build_kind_contract(
                spec,
                project,
                "profileless-test",
            )["validatorConfig"]

        self.assertEqual(
            config["finalizer"],
            "access.sample.io/accessbundle-finalizer",
        )
        self.assertEqual(
            config["managedResources"][0],
            {
                "resource": "clusterrole",
                "name": "managed-access",
                "deletionPolicy": "explicit-delete",
                "updatePolicy": "in-place",
            },
        )
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
            self.assertIn(":profileless-", contract["image"])

    def test_namespace_contract_creates_setup_and_retain_rules(
        self,
    ) -> None:
        spec = {
            "project": {
                "name": "namespace-policy-operator",
                "domain": "sample.io",
                "module": "sample.io/namespace-policy-operator",
            },
            "api": {
                "kind": "NamespaceLabelPolicy",
                "plural": "namespacelabelpolicies",
                "version": "v1alpha1",
                "group": "policy",
                "domain": "sample.io",
            },
            "specFields": [
                {"name": "namespaceName", "type": "string"},
                {"name": "labels", "type": "map[string]string"},
            ],
            "statusFields": [
                {"name": "phase", "type": "string"},
            ],
            "controller": {"managedResources": ["Namespace"]},
            "rbac": {"resources": []},
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "namespace-policy-operator"
            sample = (
                project
                / "config"
                / "samples"
                / "policy_v1alpha1_namespacelabelpolicy.yaml"
            )
            sample.parent.mkdir(parents=True, exist_ok=True)
            sample.write_text(
                """
apiVersion: policy.sample.io/v1alpha1
kind: NamespaceLabelPolicy
metadata:
  name: namespace-policy-sample
spec:
  namespaceName: target-namespace
  labels:
    environment: development
""",
                encoding="utf-8",
            )

            config = build_kind_contract(
                spec,
                project,
                "profileless-test",
            )["validatorConfig"]

        self.assertEqual(
            config["setupResources"][0]["metadata"]["name"],
            "target-namespace",
        )
        self.assertEqual(
            config["managedResources"][0]["deletionPolicy"],
            "retain",
        )
        self.assertEqual(
            config["updateSpec"]["labels"]["profileless-e2e"],
            "updated",
        )
        self.assertEqual(
            config["updateAssertions"][0]["path"],
            "metadata.labels.profileless-e2e",
        )
        self.assertIn(
            {
                "verb": "update",
                "resource": "namespaces",
                "apiGroup": "",
            },
            config["rbacChecks"],
        )

    def test_image_digest_changes_with_generated_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            controller = project / "internal" / "controller.go"
            controller.parent.mkdir(parents=True)
            controller.write_text("package internal\n", encoding="utf-8")
            before = project_content_digest(project)
            controller.write_text(
                "package internal\n// changed\n",
                encoding="utf-8",
            )
            after = project_content_digest(project)

        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
