"""Tests for structured Tool failure normalization."""

from __future__ import annotations

import unittest

from agent.error_taxonomy import ErrorCode, normalize_tool_result


class ErrorTaxonomyTest(unittest.TestCase):
    def test_rbac_failure_extracts_code_resource_and_verb(self) -> None:
        result = normalize_tool_result(
            {
                "exitCode": 1,
                "status": "failed",
                "stderr": "forbidden: denied to patch deployments",
            },
            "kind_deployment",
        )

        self.assertEqual(result["errorCode"], ErrorCode.RBAC_FORBIDDEN.value)
        self.assertEqual(result["errorDetails"]["verb"], "patch")
        self.assertEqual(result["errorDetails"]["resource"], "deployments")
        self.assertFalse(result["errorDetails"]["retryable"])

    def test_docker_failure_is_retryable_infrastructure_error(self) -> None:
        result = normalize_tool_result(
            {
                "exitCode": 1,
                "status": "failed",
                "stderr": "Cannot connect to the Docker daemon",
            },
            "kind_deployment",
        )

        self.assertEqual(
            result["errorCode"],
            ErrorCode.DOCKER_DAEMON_UNAVAILABLE.value,
        )
        self.assertTrue(result["errorDetails"]["retryable"])

    def test_success_has_no_error_details(self) -> None:
        result = normalize_tool_result(
            {"exitCode": 0, "status": "succeeded"},
            "validation",
        )

        self.assertEqual(result["errorCode"], "")
        self.assertNotIn("errorDetails", result)

    def test_native_tool_error_wins_over_legacy_text_inference(self) -> None:
        result = normalize_tool_result(
            {
                "exitCode": 2,
                "status": "failed",
                "stderr": (
                    "forbidden legacy text\n"
                    'TOOL_ERROR_JSON={"errorCode":"REQUIRED_INPUT_MISSING",'
                    '"category":"contract","message":"kind is missing",'
                    '"stage":"spec-generation","resource":"",'
                    '"verb":"","retryable":false}'
                ),
            },
            "spec_generator",
        )

        self.assertEqual(
            result["errorCode"],
            ErrorCode.REQUIRED_INPUT_MISSING.value,
        )
        self.assertEqual(result["errorDetails"]["message"], "kind is missing")
