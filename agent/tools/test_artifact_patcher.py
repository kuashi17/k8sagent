"""Tests for generic artifact patching behavior."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.tools.artifact_patcher import normalize_spec, patch_controller
from agent.tools.scaffold_runner import build_execution_env


class ArtifactPatcherTest(unittest.TestCase):
    @patch.dict("os.environ", {"GOFLAGS": "-mod=readonly"}, clear=False)
    def test_scaffold_execution_disables_vcs_stamping(self) -> None:
        env = build_execution_env()

        self.assertIn("-mod=readonly", env["GOFLAGS"])
        self.assertIn("-buildvcs=false", env["GOFLAGS"])

    def test_status_fields_add_status_subresource_rbac(self) -> None:
        model = normalize_spec(
            {
                "project": {"name": "widget-operator"},
                "api": {
                    "kind": "Widget",
                    "plural": "widgets",
                    "version": "v1alpha1",
                    "group": "apps",
                    "domain": "example.io",
                },
                "specFields": [{"name": "enabled", "type": "bool"}],
                "statusFields": [{"name": "phase", "type": "string"}],
                "rbac": {
                    "resources": [
                        {
                            "apiGroup": "apps.example.io",
                            "resource": "widgets",
                            "verbs": ["get", "list", "watch"],
                        }
                    ]
                },
            },
            {},
            None,
        )

        self.assertIn(
            {
                "apiGroup": "apps.example.io",
                "resource": "widgets/status",
                "verbs": ["get", "update", "patch"],
            },
            model["rbacResources"],
        )

    def test_controller_marker_patch_does_not_require_scaffold_comment(self) -> None:
        model = {
            "api": {"kind": "Widget"},
            "rbacResources": [
                {
                    "apiGroup": "apps.example.io",
                    "resource": "widgets",
                    "verbs": ["get", "list", "watch"],
                }
            ],
        }
        controller = """package controller

type WidgetReconciler struct {
\tClient any
}

// +kubebuilder:rbac:groups=apps.example.io,resources=widgets,verbs=get

func (r *WidgetReconciler) Reconcile() {}
"""

        patched = patch_controller(controller, model)

        self.assertIn(
            "resources=widgets,verbs=get;list;watch",
            patched,
        )

    def test_profile_rbac_and_controller_patch_are_idempotent(self) -> None:
        model = normalize_spec(
            {
                "project": {"name": "widget-operator"},
                "api": {
                    "kind": "Widget",
                    "plural": "widgets",
                    "version": "v1alpha1",
                    "group": "apps",
                    "domain": "example.io",
                },
                "specFields": [{"name": "enabled", "type": "bool"}],
                "statusFields": [{"name": "phase", "type": "string"}],
                "rbac": {"resources": []},
            },
            {
                "artifactPatcher": {
                    "rbacResources": [
                        {
                            "apiGroup": "",
                            "resource": "secrets",
                            "verbs": ["get"],
                        }
                    ],
                    "controllerPatches": [
                        {
                            "before": "func marker() {}",
                            "after": "func marker() { /* profile */ }",
                        }
                    ],
                }
            },
            "profiles/widget.yaml",
        )
        controller = """package controller

type WidgetReconciler struct {
\tClient any
}

// +kubebuilder:rbac:groups=apps.example.io,resources=widgets,verbs=get

func marker() {}
"""

        once = patch_controller(controller, model)
        twice = patch_controller(once, model)

        self.assertEqual(once, twice)
        self.assertIn('groups="",resources=secrets,verbs=get', once)
        self.assertIn("/* profile */", once)


if __name__ == "__main__":
    unittest.main()
