"""Tests for schema-validated capability proposal and approval flow."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from agent.tools.capability_drafter import (
    apply_proposal,
    approved_proposal_path,
    draft_capabilities,
    load_combined_catalog,
    proposal_digest,
    verify_discovery_approval,
)
from agent.tools.capability_discovery import CapabilityDiscoveryResult


class CapabilityDrafterTest(unittest.TestCase):
    @patch("agent.tools.capability_drafter.validate_proposal_discovery")
    def test_approval_rechecks_unchanged_discovery_contract(
        self,
        validate_discovery,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            proposal = draft_capabilities(
                self.write_spec(root),
                candidate_path=self.write_candidate(root),
                catalog_path=self.write_catalog(root),
                override_path=root / "overrides.yaml",
            )
            result = CapabilityDiscoveryResult(
                kind="NetworkPolicy",
                apiVersion="networking.k8s.io/v1",
                endpoint="/apis/networking.k8s.io/v1",
                resource="networkpolicies",
                scope="Namespaced",
                supportedVerbs=["create", "delete", "get", "list", "patch", "update", "watch"],
                requiredVerbs=["get", "list", "watch", "create", "update", "patch", "delete"],
                rbacApiGroup="networking.k8s.io",
                rbacResource="networkpolicies",
                rbacVerbs=["get", "list", "watch", "create", "update", "patch", "delete"],
            )
            proposal.discoveryValidation = [result]
            validate_discovery.return_value = [result]

            verify_discovery_approval(proposal)

        validate_discovery.assert_called_once()

    def test_approval_requires_successful_discovery_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            proposal = draft_capabilities(
                self.write_spec(root),
                candidate_path=self.write_candidate(root),
                catalog_path=self.write_catalog(root),
                override_path=root / "overrides.yaml",
            )

            with self.assertRaisesRegex(ValueError, "Discovery"):
                verify_discovery_approval(proposal)

    def test_approval_path_cannot_escape_generated_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "generated"):
            approved_proposal_path("../outside-proposal.yaml")

    def test_candidate_is_pending_until_explicit_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = self.write_catalog(root)
            spec = self.write_spec(root)
            candidate = self.write_candidate(root)
            override = root / "overrides.yaml"

            proposal = draft_capabilities(
                spec,
                candidate_path=candidate,
                catalog_path=catalog,
                override_path=override,
            )

            self.assertEqual(proposal.status, "pending-approval")
            self.assertEqual(proposal.proposalId, proposal_digest(proposal))
            self.assertFalse(proposal.approved)
            self.assertFalse(override.exists())

            apply_proposal(proposal, catalog, override)

            self.assertTrue(proposal.approved)
            self.assertEqual(
                load_combined_catalog(catalog, override)
                .by_name()["NetworkPolicy"]
                .apiVersion,
                "networking.k8s.io/v1",
            )

    def test_changed_proposal_is_rejected_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = self.write_catalog(root)
            spec = self.write_spec(root)
            proposal = draft_capabilities(
                spec,
                candidate_path=self.write_candidate(root),
                catalog_path=catalog,
                override_path=root / "overrides.yaml",
            )
            reviewed = proposal.proposalId
            proposal.capabilities[0].apiVersion = "networking.k8s.io/v2"

            with self.assertRaisesRegex(ValueError, "proposalId"):
                apply_proposal(
                    proposal,
                    catalog,
                    root / "overrides.yaml",
                    expected_proposal_id=reviewed,
                    spec_path=spec,
                )

    def test_approval_is_bound_to_current_managed_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = self.write_catalog(root)
            spec = self.write_spec(root)
            proposal = draft_capabilities(
                spec,
                candidate_path=self.write_candidate(root),
                catalog_path=catalog,
                override_path=root / "overrides.yaml",
            )
            spec.write_text(
                yaml.safe_dump(
                    {"controller": {"managedResources": ["Secret"]}}
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "current operator spec"):
                apply_proposal(
                    proposal,
                    catalog,
                    root / "overrides.yaml",
                    expected_proposal_id=proposal.proposalId,
                    spec_path=spec,
                )

    def test_malicious_identity_override_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            catalog = self.write_catalog(root)
            spec = self.write_spec(root)
            candidate = self.write_candidate(
                root,
                base_object={"metadata": {"namespace": "kube-system"}},
            )

            with self.assertRaises(ValueError):
                draft_capabilities(
                    spec,
                    candidate_path=candidate,
                    catalog_path=catalog,
                    override_path=root / "overrides.yaml",
                )

    def write_catalog(self, root: Path) -> Path:
        path = root / "catalog.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "resources": [
                        {
                            "kind": "ConfigMap",
                            "apiVersion": "v1",
                            "suffix": "config",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def write_spec(self, root: Path) -> Path:
        path = root / "operator.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "controller": {
                        "managedResources": ["NetworkPolicy"]
                    }
                }
            ),
            encoding="utf-8",
        )
        return path

    def write_candidate(
        self,
        root: Path,
        *,
        base_object: dict | None = None,
    ) -> Path:
        path = root / "candidate.yaml"
        path.write_text(
            yaml.safe_dump(
                {
                    "resources": [
                        {
                            "kind": "NetworkPolicy",
                            "apiVersion": "networking.k8s.io/v1",
                            "suffix": "network-policy",
                            "baseObject": base_object
                            if base_object is not None
                            else {"spec": {"podSelector": {}}},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        return path


if __name__ == "__main__":
    unittest.main()
