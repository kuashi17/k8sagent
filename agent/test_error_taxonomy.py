"""Tests for structured Tool failure normalization."""

from __future__ import annotations

import unittest

from agent.error_registry import ERROR_REGISTRY, ErrorCode, get_error_definition
from agent.error_taxonomy import infer_tool_error, normalize_tool_result


class ErrorTaxonomyTest(unittest.TestCase):
    def test_docker_info_step_is_structured_without_verbose_stderr(self) -> None:
        result = infer_tool_error(
            {
                "deploymentSummary": {
                    "failedStep": "docker-info",
                    "error": "command failed exitCode=1",
                }
            },
            "kind_deployment",
        )

        self.assertEqual(
            result["errorCode"],
            "DOCKER_DAEMON_UNAVAILABLE",
        )

    def test_kind_cluster_creation_failure_is_infrastructure_error(self) -> None:
        result = infer_tool_error(
            {
                "deploymentSummary": {
                    "failedStep": "kind-create-cluster",
                    "error": "failed to get api server port: UtilAcceptVsock",
                }
            },
            "kind_deployment",
        )

        self.assertEqual(result["errorCode"], "KIND_CONNECTION_FAILED")
        self.assertTrue(result["retryable"])

    def test_registry_covers_every_non_empty_error_code(self) -> None:
        expected = {code.value for code in ErrorCode if code is not ErrorCode.NONE}
        self.assertEqual(set(ERROR_REGISTRY), expected)

    def test_registry_is_the_source_for_recovery_retry_and_ui(self) -> None:
        contract = get_error_definition(ErrorCode.COMMAND_TIMEOUT)

        self.assertEqual(contract.recoveryClassification, "command-timeout")
        self.assertEqual(
            contract.recoveryPolicy,
            "retry-after-environment-recovery",
        )
        self.assertTrue(contract.retryable)
        self.assertEqual(contract.uiSeverity, "warning")
        self.assertTrue(contract.userMessage)

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
        self.assertEqual(
            result["errorDetails"]["uiSeverity"],
            "error",
        )

    def test_common_local_environment_failures_have_distinct_codes(self) -> None:
        cases = [
            (
                "error: context kind-old-cluster does not exist",
                ErrorCode.KUBECTL_CONTEXT_INVALID,
            ),
            (
                "ollama request failed: connection refused",
                ErrorCode.OLLAMA_UNAVAILABLE,
            ),
            (
                "Ollama local LLM endpoint에 연결할 수 없습니다. 요청이 90초 안에 끝나지 않았습니다.",
                ErrorCode.OLLAMA_UNAVAILABLE,
            ),
            (
                "listen tcp 0.0.0.0:8000: bind: address already in use",
                ErrorCode.PORT_CONFLICT,
            ),
            (
                "operation timed out waiting for deployment",
                ErrorCode.COMMAND_TIMEOUT,
            ),
        ]

        for stderr, expected in cases:
            with self.subTest(expected=expected.value):
                result = normalize_tool_result(
                    {"exitCode": 1, "stderr": stderr},
                    "kind_deployment",
                )
                self.assertEqual(result["errorCode"], expected.value)
                self.assertTrue(result["errorDetails"]["retryable"])
                self.assertEqual(
                    result["errorDetails"]["category"],
                    "infrastructure",
                )

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
