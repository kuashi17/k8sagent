"""Tests for profile kind matrix command construction."""

from __future__ import annotations

import json
import unittest

from agent.evaluation.profile_kind_matrix import (
    build_command,
    missing_fixture_reason,
    parse_summary,
)


class ProfileKindMatrixTest(unittest.TestCase):
    def test_missing_untracked_profile_fixture_is_skipped(self) -> None:
        reason = missing_fixture_reason(
            {
                "project": "workspace/not-tracked-project",
                "sample": "workspace/not-tracked-project/sample.yaml",
            }
        )

        self.assertIn("not available in this checkout", reason)
        self.assertIn("profileless kind matrix", reason)

    def test_last_json_object_is_used_as_deployment_summary(self) -> None:
        summary = parse_summary(
            'progress\n{"status":"succeeded","checks":{"ok":true}}\n'
        )

        self.assertEqual(summary["status"], "succeeded")
        self.assertTrue(summary["checks"]["ok"])

    def test_profile_capability_becomes_runner_command(self) -> None:
        command = build_command(
            {
                "project": "workspace/example",
                "clusterName": "example",
                "image": "example:kind",
                "sample": "workspace/example/sample.yaml",
                "namespace": "example-system",
                "deployment": "example-controller-manager",
                "validator": "managed-resources",
                "validatorConfig": {"resource": "example"},
                "skipPrepareController": True,
                "skipPrevalidation": False,
            }
        )

        self.assertIn("--skip-prepare-controller", command)
        self.assertNotIn("--skip-prevalidation", command)
        config = json.loads(command[command.index("--validator-config") + 1])
        self.assertEqual(config["resource"], "example")


if __name__ == "__main__":
    unittest.main()
