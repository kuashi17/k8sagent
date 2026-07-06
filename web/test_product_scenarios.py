"""Three representative product scenarios for release confidence."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.capability_support import support_for
from agent.tools.spec_generator import generate_spec
from web.result_presenter import present_kind_validation_result, present_run_result


class ProductScenarioTest(unittest.TestCase):
    def test_new_cr_using_stable_deployment_pattern(self) -> None:
        spec = generate_spec(
            """
CustomerPortal라는 Custom Resource를 만들고 싶습니다.
API는 portal.sample.io/v1alpha1입니다.
spec:
- image: string
- replicas: int32
status:
- phase: string
- readyReplicas: int32
Controller는 Deployment를 생성·갱신하고 외부 변경을 spec 기준으로 복구합니다.
CustomerPortal을 삭제하면 Deployment도 함께 삭제합니다.
""",
            Path("requirements/product-stable.txt"),
        )
        capability = support_for(spec["controller"]["managedResources"])
        result = present_run_result(
            {
                "state": "succeeded",
                "jobType": "requirement",
                "summary": {
                    "agentMode": "dry-run",
                    "agentResult": {
                        "status": "planned",
                        "succeeded": True,
                        "canExecute": True,
                        "technicalDetails": {
                            "kind": spec["api"]["kind"],
                            "managedResources": spec["controller"]["managedResources"],
                            "capabilitySupport": capability,
                        },
                    },
                },
            }
        )

        self.assertEqual(result.kind, "CustomerPortal")
        self.assertEqual(result.managed_resources, ["Deployment"])
        self.assertEqual(capability[0]["level"], "stable")
        self.assertFalse(result.has_experimental_capability)

    def test_network_policy_pattern_is_experimental_without_service_fallback(self) -> None:
        spec = generate_spec(
            """
AppAccessPolicy라는 Custom Resource를 만들고 싶습니다.
API는 security.sample.io/v1alpha1입니다.
spec:
- appSelector: map[string]string
- allowedPort: int32
status:
- phase: string
Controller는 NetworkPolicy만 생성하고 관리합니다.
Deployment, Pod, Service는 생성하지 마세요.
""",
            Path("requirements/product-experimental.txt"),
        )
        capability = support_for(spec["controller"]["managedResources"])

        self.assertEqual(spec["controller"]["managedResources"], ["NetworkPolicy"])
        self.assertEqual(capability[0]["level"], "experimental")
        self.assertTrue(
            {"deployments", "pods", "services"}.isdisjoint(
                item["resource"] for item in spec["rbac"]["resources"]
            )
        )

    def test_docker_failure_is_environment_failure_not_operator_failure(self) -> None:
        result = present_kind_validation_result(
            {
                "state": "failed",
                "stderrTail": "Cannot connect to the Docker daemon",
                "kindValidation": {
                    "status": "failed",
                    "results": [
                        {
                            "status": "failed",
                            "deploymentSummary": {"failedStep": "docker-info"},
                        }
                    ],
                },
            }
        )

        self.assertEqual(result.outcome, "infrastructure-failed")
        self.assertEqual(result.error_code, "DOCKER_DAEMON_UNAVAILABLE")
        self.assertFalse(result.capability_evidence_eligible)
        self.assertTrue(result.retryable)


if __name__ == "__main__":
    unittest.main()
