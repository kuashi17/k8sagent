"""Tests for the generic kind deployment engine/validator contract."""

from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from agent.tools.kind_deployment_runner import (
    KindDeploymentEngine,
    build_runtime_evidence,
)
from agent.tools.kind_deployment_runner import is_transient_docker_failure
from agent.tools.kind_deployment_validators import (
    ManagedResourceValidator,
    create_validator,
    drift_value,
    get_path,
    json_pointer,
    normalized_resource_snapshot,
)


class KindDeploymentValidatorTest(unittest.TestCase):
    def test_runtime_evidence_has_stable_quality_dimensions(self) -> None:
        result = build_runtime_evidence(
            {
                "lifecycleIdempotency": {"reapplyStable": True},
                "lifecycleDriftRecovery": {"recovered": True},
                "rbacPreflight": [{"allowed": True}],
                "rbacLeastPrivilege": {"passed": True},
                "lifecycleDelete": {
                    "customResourceAbsent": True,
                    "managedResources": {
                        "deployment/sample": {"passed": True}
                    },
                },
                "stateMachineStatus": {
                    "observedGeneration": 2,
                    "conditions": [{"type": "Ready"}],
                },
            }
        )

        self.assertEqual(result["idempotency"]["status"], "passed")
        self.assertEqual(result["driftRecovery"]["status"], "passed")
        self.assertEqual(
            result["rbacLeastPrivilege"]["status"], "passed"
        )
        self.assertEqual(result["finalizer"]["status"], "not-applicable")

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

    def test_unknown_validator_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported kind deployment validator"):
            create_validator("unknown", {})

    def test_managed_resource_validator_uses_lifecycle_contract(self) -> None:
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
                    "ownership": "none",
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
                for item in validator.planned_steps(True)
            ],
        )
        self.assertIn(
            "verify-idempotency",
            [
                item["name"]
                for item in validator.planned_steps(True)
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
        self.assertEqual(
            json_pointer(
                "spec.template.spec.containers[0].ports[0].containerPort"
            ),
            "/spec/template/spec/containers/0/ports/0/containerPort",
        )
        self.assertEqual(drift_value(2), 39)
        self.assertEqual(
            drift_value({"mode": "safe"}),
            {"mode": "safe-drift"},
        )
        self.assertEqual(
            drift_value(
                {"token": "dmFsdWU="},
                resource="secret",
                path="data",
            ),
            {"token": "ZHJpZnQ="},
        )

    def test_final_evidence_is_refetched_after_readiness_waits(self) -> None:
        validator = ManagedResourceValidator(
            {
                "resource": "customerportal",
                "sampleName": "sample",
                "managedResources": [
                    {"resource": "deployment", "name": "sample-deployment"}
                ],
            }
        )
        engine = Mock()
        engine.checks = {
            "managedResources": [
                {"status": {"unavailableReplicas": 1}}
            ],
            "customResourceStatus": {"phase": "Progressing"},
        }
        validator.wait_present = Mock(
            side_effect=[
                {"status": {"readyReplicas": 1, "availableReplicas": 1}},
                {
                    "status": {
                        "phase": "Ready",
                        "readyReplicas": 1,
                    }
                },
            ]
        )

        validator.capture_stable_evidence(engine)

        self.assertEqual(
            engine.checks["managedResources"][0]["status"]["readyReplicas"],
            1,
        )
        self.assertEqual(
            engine.checks["customResourceStatus"],
            {"phase": "Ready", "readyReplicas": 1},
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
                "validator": "managed-resources",
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
                "validator": "managed-resources",
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

if __name__ == "__main__":
    unittest.main()
