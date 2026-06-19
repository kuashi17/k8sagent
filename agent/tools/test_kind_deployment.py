"""Tests for the generic kind deployment engine/validator contract."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from agent.tools.kind_deployment_runner import KindDeploymentEngine
from agent.tools.kind_deployment_validators import AppConfigConfigMapValidator, create_validator
from agent.tools.langchain_wrappers import kind_deployment_runner


class KindDeploymentValidatorTest(unittest.TestCase):
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
