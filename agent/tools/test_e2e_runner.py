"""Contract tests for the legacy Job-workload e2e adapter."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from agent.tools import langchain_wrappers
from agent.tools.e2e_runner import (
    build_profile_config,
    load_profile,
    load_sample_expectations,
)
from agent.tools.e2e_profile_contract import JOB_WORKLOAD_VALIDATOR
from agent.tools.log_analyzer import recommended_command


REPO_ROOT = Path(__file__).resolve().parents[2]


class E2ERunnerContractTest(unittest.TestCase):
    def test_training_profile_satisfies_explicit_contract(self) -> None:
        profile = load_profile(REPO_ROOT / "profiles" / "trainingjob.yaml")

        self.assertEqual(profile["e2e"]["validator"], JOB_WORKLOAD_VALIDATOR)
        self.assertEqual(
            profile["e2e"]["customResource"]["crdName"],
            "trainingjobs.ml.ai.sample.io",
        )

    def test_profile_contract_has_no_trainingjob_fallback(self) -> None:
        source = yaml.safe_load(
            (REPO_ROOT / "profiles" / "trainingjob.yaml").read_text(
                encoding="utf-8"
            )
        )
        source["profileName"] = "batch-workload"
        source["e2e"]["customResource"] = {
            "resource": "batchrequest",
            "crdName": "batchrequests.compute.example.io",
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.yaml"
            path.write_text(
                yaml.safe_dump(source, sort_keys=False),
                encoding="utf-8",
            )
            profile = load_profile(path)

        config = build_profile_config(
            profile,
            {
                "crName": "batch-sample",
                "image": "worker:latest",
                "gpuCount": 0,
                "pvcName": "data",
                "datasetPath": "/data/input",
                "outputPath": "/data/output",
            },
            "profiles/batch-workload.yaml",
        )

        self.assertEqual(config["profileName"], "batch-workload")
        self.assertEqual(config["crResource"], "batchrequest")
        self.assertEqual(
            config["crdName"],
            "batchrequests.compute.example.io",
        )
        self.assertNotIn("trainingjob", str(config).lower())

    def test_incomplete_profile_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "profile.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "profileName": "unsafe-default",
                        "managedResources": ["Job"],
                        "referencedResources": [
                            "Pod",
                            "PersistentVolumeClaim",
                        ],
                        "e2e": {"clusterName": "missing-contract"},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                SystemExit,
                f"{JOB_WORKLOAD_VALIDATOR} contract",
            ):
                load_profile(path)

    def test_sample_missing_required_workload_fields_is_rejected(self) -> None:
        profile = load_profile(REPO_ROOT / "profiles" / "trainingjob.yaml")
        profile["sampleDefaults"] = {}
        with tempfile.TemporaryDirectory() as temp:
            sample = Path(temp) / "sample.yaml"
            sample.write_text(
                yaml.safe_dump(
                    {
                        "metadata": {"name": "incomplete"},
                        "spec": {"image": "worker:latest"},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "sample does not satisfy"):
                load_sample_expectations(sample, profile)

    def test_wrapper_refuses_profileless_legacy_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a profile"):
            langchain_wrappers.e2e_runner(
                input_spec="generated/operator-spec.yaml"
            )

    def test_log_rerun_command_preserves_required_profile(self) -> None:
        command = recommended_command(
            {
                "projectDir": "workspace/operator",
                "clusterName": "legacy-e2e",
                "sample": "workspace/operator/sample.yaml",
                "profileConfig": {
                    "profilePath": "profiles/job-workload.yaml"
                },
            },
            Path("logs/e2e/example"),
        )

        self.assertIn("--profile profiles/job-workload.yaml", command)

    def test_log_rerun_without_profile_is_not_suggested(self) -> None:
        command = recommended_command(
            {
                "projectDir": "workspace/operator",
                "clusterName": "legacy-e2e",
                "sample": "workspace/operator/sample.yaml",
            },
            Path("logs/e2e/example"),
        )

        self.assertIn("충분한 정보가 없어", command)


if __name__ == "__main__":
    unittest.main()
