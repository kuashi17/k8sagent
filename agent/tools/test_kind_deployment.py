"""Tests for the generic kind deployment engine/validator contract."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from agent.tools.kind_deployment_runner import KindDeploymentEngine
from agent.tools.kind_deployment_runner import is_transient_docker_failure
from agent.tools.kind_deployment_validators import (
    AppConfigConfigMapValidator,
    ManagedResourceValidator,
    create_validator,
    get_path,
    normalized_resource_snapshot,
)
from agent.tools.langchain_wrappers import kind_deployment_runner


class KindDeploymentValidatorTest(unittest.TestCase):
    def test_only_known_transient_docker_errors_are_retryable(self) -> None:
        self.assertTrue(
            is_transient_docker_failure(
                {"stderr": "UtilAcceptVsock failed: error getting credentials"}
            )
        )
        self.assertFalse(
            is_transient_docker_failure(
                {"stderr": "Dockerfile syntax error on line 2"}
            )
        )

    def test_state_machine_status_requires_matching_ready_generation(
        self,
    ) -> None:
        validator = ManagedResourceValidator(
            {
                "resource": "examples",
                "sampleName": "sample",
                "managedResources": [],
            }
        )
        validator.verify_state_machine_status(
            {"metadata": {"generation": 3}},
            {
                "observedGeneration": 3,
                "conditions": [
                    {
                        "type": "Ready",
                        "status": "True",
                        "observedGeneration": 3,
                    }
                ],
            },
        )
        with self.assertRaisesRegex(RuntimeError, "Ready condition"):
            validator.verify_state_machine_status(
                {"metadata": {"generation": 3}},
                {
                    "observedGeneration": 3,
                    "conditions": [],
                },
            )

    def test_appconfig_validator_exposes_profile_specific_plan(self) -> None:
        validator = create_validator(
            "appconfig-configmap",
            {
                "resource": "appconfig",
                "sampleName": "sample",
                "configMapName": "sample-config",
                "namespace": "sample-system",
            },
        )

        steps = validator.planned_steps(include_prepare=False, include_lifecycle=True)

        self.assertIsInstance(validator, AppConfigConfigMapValidator)
        self.assertEqual(steps[0]["name"], "verify-appconfig-configmap-and-status")
        self.assertTrue(all(step["validator"] == "appconfig-configmap" for step in steps))
        self.assertEqual(validator.summary()["managedResource"]["kind"], "ConfigMap")
        self.assertEqual(
            validator.kubectl(["get", "appconfig", "sample"]),
            [
                "kubectl",
                "--namespace",
                "sample-system",
                "get",
                "appconfig",
                "sample",
            ],
        )

    def test_unknown_validator_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported kind deployment validator"):
            create_validator("unknown", {})

    def test_managed_resource_validator_uses_profile_contract(self) -> None:
        validator = create_validator(
            "managed-resources",
            {
                "resource": "trainingjob",
                "sampleName": "sample",
                "managedResources": [
                    {
                        "resource": "job",
                        "name": "sample-job",
                        "deletionPolicy": "retain",
                    }
                ],
                "updateSpec": {"image": "busybox:1.36"},
                "initialAssertions": [
                    {
                        "resource": "job",
                        "name": "sample-job",
                        "path": "spec.parallelism",
                        "equals": 1,
                    }
                ],
                "updateAssertions": [
                    {
                        "resource": "job",
                        "name": "sample-job",
                        "path": "spec.parallelism",
                        "equals": 2,
                    }
                ],
                "rbacChecks": [
                    {
                        "verb": "create",
                        "resource": "jobs",
                        "apiGroup": "batch",
                    }
                ],
            },
        )

        self.assertIsInstance(validator, ManagedResourceValidator)
        self.assertEqual(
            validator.summary()["managedResources"],
            [
                {
                    "resource": "job",
                    "name": "sample-job",
                    "deletionPolicy": "retain",
                    "updatePolicy": "in-place",
                }
            ],
        )
        self.assertEqual(validator.rbac_checks()[0]["verb"], "create")
        self.assertEqual(
            validator.summary()["initialAssertions"][0]["equals"],
            1,
        )
        self.assertIn(
            "verify-update",
            [
                item["name"]
                for item in validator.planned_steps(True, True)
            ],
        )
        self.assertIn(
            "verify-idempotency",
            [
                item["name"]
                for item in validator.planned_steps(True, True)
            ],
        )

    def test_get_path_supports_nested_list_indexes(self) -> None:
        value = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {"ports": [{"containerPort": 8080}]}
                        ]
                    }
                }
            }
        }

        self.assertEqual(
            get_path(
                value,
                (
                    "spec.template.spec.containers[0]."
                    "ports[0].containerPort"
                ),
            ),
            8080,
        )

    def test_recreate_update_is_driven_by_controller_contract(self) -> None:
        validator = ManagedResourceValidator(
            {
                "resource": "storagepolicy",
                "sampleName": "sample",
                "namespace": "sample-system",
                "managedResources": [
                    {
                        "resource": "persistentvolumeclaim",
                        "name": "sample-claim",
                        "updatePolicy": "recreate",
                    }
                ],
                "updateSpec": {"accessModes": ["ReadOnlyMany"]},
                "updateMode": "recreate",
                "updateAssertions": [
                    {
                        "resource": "persistentvolumeclaim",
                        "name": "sample-claim",
                        "path": "spec.accessModes",
                        "equals": ["ReadOnlyMany"],
                    }
                ],
            }
        )
        engine = Mock()
        engine.checks = {}
        engine.run_cmd.return_value = {
            "exitCode": 0,
            "stdout": "",
            "stderr": "",
        }

        with patch.object(
            validator,
            "wait_assertion",
            return_value={"passed": True},
        ):
            validator.verify_update(engine)

        names = [call.args[0] for call in engine.run_cmd.call_args_list]
        self.assertIn("kubectl-patch-custom-resource", names)
        self.assertFalse(
            any(name.startswith("kubectl-delete-recreate-") for name in names)
        )

    def test_declarative_assertion_and_snapshot_helpers(self) -> None:
        resource = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": "sample",
                "resourceVersion": "17",
                "uid": "volatile",
                "labels": {"app": "sample"},
            },
            "spec": {"replicas": 2},
            "status": {"readyReplicas": 1},
        }

        self.assertEqual(get_path(resource, "spec.replicas"), 2)
        snapshot = normalized_resource_snapshot(resource)
        self.assertNotIn("resourceVersion", snapshot["metadata"])
        self.assertNotIn("uid", snapshot["metadata"])
        self.assertNotIn("status", snapshot)

    def test_engine_uses_deployment_namespace_as_validator_default(self) -> None:
        args = type(
            "Args",
            (),
            {
                "project": "workspace/example",
                "sample": "config/samples/example.yaml",
                "timeout": "30s",
                "validator_config": "{}",
                "sample_name": "",
                "configmap_name": "",
                "validator": "appconfig-configmap",
                "namespace": "example-system",
            },
        )()

        engine = KindDeploymentEngine(args)

        self.assertEqual(engine.validator.namespace, "example-system")

    @patch.object(KindDeploymentEngine, "run_cmd")
    def test_engine_activates_target_kind_context(self, run_cmd) -> None:
        args = type(
            "Args",
            (),
            {
                "project": "workspace/example",
                "sample": "config/samples/example.yaml",
                "timeout": "30s",
                "validator_config": "{}",
                "sample_name": "",
                "configmap_name": "",
                "validator": "appconfig-configmap",
                "namespace": "example-system",
                "cluster_name": "example",
            },
        )()
        engine = KindDeploymentEngine(args)

        engine.activate_context()

        run_cmd.assert_called_once_with(
            "kubectl-use-context",
            ["kubectl", "config", "use-context", "kind-example"],
            timeout=30,
        )

    @patch("agent.tools.langchain_wrappers.run_command")
    def test_wrapper_passes_validator_as_json_contract(self, run_command) -> None:
        run_command.return_value = {"stdout": "{}", "stderr": "", "exitCode": 0, "status": "succeeded"}

        kind_deployment_runner(
            "workspace/example",
            cluster_name="example",
            image="example:kind",
            sample="config/samples/example.yaml",
            namespace="example-system",
            deployment="example-controller-manager",
            validator="appconfig-configmap",
            validator_config={"resource": "appconfig", "sampleName": "sample", "configMapName": "sample-config"},
        )

        command = run_command.call_args.args[0]
        config = json.loads(command[command.index("--validator-config") + 1])
        self.assertEqual(command[command.index("--validator") + 1], "appconfig-configmap")
        self.assertEqual(config["configMapName"], "sample-config")
        self.assertIn("--dry-run", command)


if __name__ == "__main__":
    unittest.main()
