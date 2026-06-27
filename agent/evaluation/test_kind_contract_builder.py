"""Tests for IR-derived kind lifecycle contracts."""

from __future__ import annotations

import unittest

from agent.evaluation.kind_contract_builder import (
    build_validation_contract,
)
from agent.tools.artifact_patcher import normalize_spec
from agent.tools.controller_ir_builder import build_controller_ir


def build_ir(
    resource: str,
    spec_fields: list[dict[str, str]],
):
    model = normalize_spec(
        {
            "project": {
                "name": "generic-operator",
                "domain": "sample.io",
                "module": "sample.io/generic-operator",
            },
            "api": {
                "kind": "GenericPolicy",
                "plural": "genericpolicies",
                "version": "v1alpha1",
                "group": "policy",
                "domain": "sample.io",
            },
            "specFields": spec_fields,
            "statusFields": [
                {"name": "phase", "type": "string"}
            ],
            "controller": {"managedResources": [resource]},
            "rbac": {"resources": []},
        },
        {},
        None,
    )
    return build_controller_ir(model)


class KindContractBuilderTest(unittest.TestCase):
    def test_patch_existing_contract_is_setup_update_and_retain(
        self,
    ) -> None:
        contract = build_validation_contract(
            build_ir(
                "Namespace",
                [
                    {"name": "namespaceName", "type": "string"},
                    {
                        "name": "labels",
                        "type": "map[string]string",
                    },
                ],
            ),
            {
                "metadata": {"name": "policy-sample"},
                "spec": {
                    "namespaceName": "target",
                    "labels": {"team": "platform"},
                },
            },
            "genericpolicies",
            "policy.sample.io",
        )

        self.assertEqual(
            contract.managedResources[0].deletionPolicy,
            "retain",
        )
        self.assertEqual(
            contract.setupResources[0]["metadata"]["name"],
            "target",
        )
        self.assertEqual(contract.updateMode, "in-place")
        self.assertEqual(
            contract.updateAssertions[0].path,
            "metadata.labels.profileless-e2e",
        )

    def test_immutable_only_update_uses_recreate_mode(self) -> None:
        ir = build_ir(
            "PersistentVolumeClaim",
            [
                {"name": "claimName", "type": "string"},
                {
                    "name": "storageClassName",
                    "type": "string",
                },
            ],
        )
        contract = build_validation_contract(
            ir,
            {
                "metadata": {"name": "claim-policy"},
                "spec": {
                    "claimName": "application-data",
                    "storageClassName": "standard",
                },
            },
            "genericpolicies",
            "policy.sample.io",
        )

        self.assertEqual(contract.updateMode, "recreate")
        self.assertEqual(
            contract.managedResources[0].updatePolicy,
            "recreate",
        )
        self.assertEqual(
            contract.updateSpec,
            {"storageClassName": "standard-updated"},
        )

    def test_generic_numeric_mapping_builds_update_assertion(
        self,
    ) -> None:
        contract = build_validation_contract(
            build_ir(
                "DaemonSet",
                [
                    {"name": "image", "type": "string"},
                    {"name": "port", "type": "int32"},
                ],
            ),
            {
                "metadata": {"name": "node-agent"},
                "spec": {"image": "nginx:latest", "port": 8080},
            },
            "genericpolicies",
            "policy.sample.io",
        )

        self.assertEqual(contract.updateSpec, {"port": 8081})
        self.assertEqual(
            contract.updateAssertions[0].path,
            "spec.template.spec.containers[0].ports[0].containerPort",
        )


if __name__ == "__main__":
    unittest.main()
