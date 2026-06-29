"""Tests for beginner-facing Agent result summaries."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from agent.tools.capability_drafter import ProposalModel, proposal_digest
from agent.tools.capability_discovery import CapabilityDiscoveryResult
from agent.tools.resource_catalog import ResourceCapabilityDefinition
from web.result_presenter import present_run_result


class ResultPresenterTest(unittest.TestCase):
    def test_read_only_resource_is_presented_separately(self) -> None:
        result = present_run_result(
            {
                "state": "succeeded",
                "jobType": "requirement",
                "summary": {
                    "agentMode": "dry-run",
                    "requirementSummary": {
                        "kind": "DeploymentHealth",
                        "managedResources": [],
                        "observedResources": ["Deployment"],
                    },
                },
            }
        )

        self.assertEqual(result.managed_resources, [])
        self.assertEqual(result.observed_resources, ["Deployment"])

    def test_legacy_english_actions_are_presented_in_korean(self) -> None:
        result = present_run_result(
            {
                "state": "succeeded",
                "jobType": "requirement",
                "summary": {
                    "agentMode": "dry-run",
                    "agentResult": {
                        "beginnerSummary": (
                            "A deterministic summary was built from validated Tool exit codes."
                        ),
                        "technicalDetails": {
                            "warnings": [
                                "Final LLM evaluation skipped by fast mode."
                            ],
                            "nextActions": [
                                "Review validated Tool calls and generated artifacts.",
                                "Use execute mode only after reviewing safety-evaluation.json.",
                            ],
                        },
                    },
                },
            }
        )

        self.assertEqual(
            result.summary,
            "검증된 작업 결과를 바탕으로 실행 요약을 만들었습니다.",
        )
        self.assertEqual(
            result.next_actions,
            [
                "생성 계획과 안전 검사 결과를 확인합니다.",
                "문제가 없으면 화면에서 실제 생성을 승인해 코드 생성과 검증을 진행합니다.",
            ],
        )
        self.assertEqual(
            result.warnings,
            ["빠른 계획 모드에서는 최종 LLM 평가를 생략했습니다."],
        )

    def test_dry_run_exposes_review_then_execute_action(self) -> None:
        result = present_run_result(
            {
                "state": "succeeded",
                "jobType": "requirement",
                "summary": {
                    "agentMode": "dry-run",
                    "requirementSummary": {
                        "kind": "WebService",
                        "managedResources": [
                            "Deployment",
                            "Service",
                        ],
                        "shortSummary": "Deployment와 Service를 관리합니다.",
                    },
                    "toolResults": [
                        {"tool": "spec_generator", "exitCode": 0}
                    ],
                    "generatedFiles": {
                        "operatorSpec": "generated/webservice.yaml"
                    },
                    "warnings": [],
                    "errors": [],
                    "nextRecommendedActions": ["계획을 검토합니다."],
                    "finalLLM": {"output": {}},
                },
            }
        )

        self.assertTrue(result.succeeded)
        self.assertTrue(result.can_execute)
        self.assertEqual(result.kind, "WebService")
        self.assertEqual(
            result.managed_resources,
            ["Deployment", "Service"],
        )
        self.assertEqual(
            result.completed_steps,
            ["요구사항 구조화"],
        )

    def test_pending_capability_is_exposed_as_separate_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated = root / "generated"
            generated.mkdir()
            proposal = ProposalModel(
                status="pending-approval",
                source="test",
                sourceSpecDigest="source",
                unsupportedResources=["QuantumQueue"],
                capabilities=[
                    ResourceCapabilityDefinition(
                        kind="QuantumQueue",
                        apiVersion="example.io/v1",
                        suffix="queue",
                    )
                ],
                discoveryValidation=[
                    CapabilityDiscoveryResult(
                        kind="QuantumQueue",
                        apiVersion="example.io/v1",
                        endpoint="/apis/example.io/v1",
                        resource="quantumqueues",
                        scope="Namespaced",
                        supportedVerbs=["create", "delete", "get", "list", "patch", "update", "watch"],
                        requiredVerbs=["get", "list", "watch", "create", "update", "patch", "delete"],
                        rbacApiGroup="example.io",
                        rbacResource="quantumqueues",
                        rbacVerbs=["get", "list", "watch", "create", "update", "patch", "delete"],
                    )
                ],
            )
            proposal.proposalId = proposal_digest(proposal)
            (generated / "queue-capability-proposal.yaml").write_text(
                yaml.safe_dump(
                    proposal.model_dump(mode="json"),
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            with patch("web.result_presenter.REPO_ROOT", root):
                result = present_run_result(
                    {
                        "state": "succeeded",
                        "jobType": "requirement",
                        "summary": {
                            "agentMode": "dry-run",
                            "requirementSummary": {
                                "kind": "QueuePolicy"
                            },
                            "generatedFiles": {
                                "capabilityProposal": (
                                    "generated/queue-capability-proposal.yaml"
                                )
                            },
                        },
                    }
                )

        self.assertEqual(result.capability_approval, proposal.proposalId)
        self.assertEqual(
            result.capability_resources,
            ["QuantumQueue · example.io/v1 · namespaced"],
        )
        self.assertIn("example.io/quantumqueues", result.capability_discovery[0])


if __name__ == "__main__":
    unittest.main()
