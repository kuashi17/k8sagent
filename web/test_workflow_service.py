"""Tests for validated Web workflow command construction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from agent.tools.capability_drafter import ProposalModel, proposal_digest
from agent.tools.resource_catalog import ResourceCapabilityDefinition
from web.schemas import RequirementRunRequest
from web.workflow_service import WorkflowService


class WorkflowServiceTest(unittest.TestCase):
    class Jobs:
        def __init__(self, parent: dict) -> None:
            self.parent = parent

        def get(self, job_id: str) -> dict:
            return self.parent if job_id == self.parent.get("jobId") else {}

    def test_execute_command_requires_contract_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profiles = root / "profiles"
            profiles.mkdir()
            service = WorkflowService(
                root,
                root / "logs" / "web",
                profiles,
            )
            request = RequirementRunRequest(
                requirement_text="Create a ConfigMap Operator.",
                mode="execute",
                confirm_execute=True,
            )
            command = service.build_requirement_command(
                request,
                root / "requirement.txt",
            )

        self.assertIn("--execute", command)
        self.assertIn("execute", command)

    def test_profile_path_cannot_escape_profile_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profiles = root / "profiles"
            profiles.mkdir()
            outside = root / "outside.yaml"
            outside.write_text("profileName: outside", encoding="utf-8")
            service = WorkflowService(
                root,
                root / "logs" / "web",
                profiles,
            )

            with self.assertRaisesRegex(ValueError, "profiles"):
                service.validate_profile("outside.yaml")

    def test_reviewed_capability_is_added_to_execute_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "profiles").mkdir()
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
            )
            proposal.proposalId = proposal_digest(proposal)
            proposal_path = generated / "queue-capability-proposal.yaml"
            proposal_path.write_text(
                yaml.safe_dump(
                    proposal.model_dump(mode="json"),
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            service = WorkflowService(
                root,
                root / "logs" / "web",
                root / "profiles",
            )
            request = RequirementRunRequest(
                requirement_text="Create a QuantumQueue Operator.",
                mode="execute",
                confirm_execute=True,
                capability_proposal="generated/queue-capability-proposal.yaml",
                capability_approval=proposal.proposalId,
                confirm_capability=True,
            )

            service.validate_capability_approval(request)
            command = service.build_requirement_command(
                request,
                root / "requirement.txt",
            )

        self.assertIn("--capability-proposal", command)
        self.assertIn(proposal.proposalId, command)

    def test_tampered_capability_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "profiles").mkdir()
            generated = root / "generated"
            generated.mkdir()
            path = generated / "proposal.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "schemaVersion": 1,
                        "proposalId": "reviewed",
                        "status": "pending-approval",
                        "source": "test",
                        "unsupportedResources": ["QuantumQueue"],
                        "capabilities": [
                            {
                                "kind": "QuantumQueue",
                                "apiVersion": "evil.io/v1",
                                "suffix": "queue",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            service = WorkflowService(
                root,
                root / "logs" / "web",
                root / "profiles",
            )
            request = RequirementRunRequest(
                requirement_text="Create a QuantumQueue Operator.",
                mode="execute",
                confirm_execute=True,
                capability_proposal="generated/proposal.yaml",
                capability_approval="reviewed",
                confirm_capability=True,
            )

            with self.assertRaisesRegex(ValueError, "변경"):
                service.validate_capability_approval(request)

    def test_parent_job_capability_artifact_can_be_approved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "profiles").mkdir()
            job_id = "20260701-parent"
            artifacts = root / "logs" / "web" / "jobs" / job_id / "artifacts"
            artifacts.mkdir(parents=True)
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
            )
            proposal.proposalId = proposal_digest(proposal)
            proposal_path = artifacts / "proposal.yaml"
            proposal_path.write_text(
                yaml.safe_dump(
                    proposal.model_dump(mode="json"),
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            service = WorkflowService(
                root,
                root / "logs" / "web",
                root / "profiles",
            )
            request = RequirementRunRequest(
                requirement_text="Create a QuantumQueue Operator.",
                mode="execute",
                confirm_execute=True,
                capability_proposal=str(proposal_path.relative_to(root)),
                capability_approval=proposal.proposalId,
                confirm_capability=True,
                approval_parent_job_id=job_id,
            )
            jobs = self.Jobs(
                {
                    "jobId": job_id,
                    "jobDir": f"logs/web/jobs/{job_id}",
                }
            )

            service.validate_capability_approval(request, jobs)


if __name__ == "__main__":
    unittest.main()
