"""Tests for recovery orchestration selection."""

from __future__ import annotations

import unittest

from agent.recovery_orchestrator import plan_recovery


class RecoveryOrchestratorTest(unittest.TestCase):
    def test_docker_failure_skips_recovery_llm(self) -> None:
        result = plan_recovery(
            {
                "requirementSummary": {},
                "targetProjectDir": "workspace/example",
                "generatedFiles": {
                    "operatorSpec": "generated/nonexistent-spec.yaml"
                },
            },
            {"llmOutput": {}},
            {"toolResults": []},
            {
                "failedTool": "kind_deployment",
                "failedStep": "docker-info",
                "stderrTail": "Cannot connect to the Docker daemon",
            },
            "execute",
            lambda value: [],
            lambda *args, **kwargs: {},
        )

        self.assertFalse(result["llmPlannerUsed"])
        self.assertEqual(result["skipReason"], "docker-kind-connection")
