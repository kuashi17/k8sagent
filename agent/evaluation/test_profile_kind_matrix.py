"""Tests for profile kind matrix command construction."""

from __future__ import annotations

import json
import unittest

from agent.evaluation.profile_kind_matrix import build_command


class ProfileKindMatrixTest(unittest.TestCase):
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
