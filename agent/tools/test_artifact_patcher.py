"""Tests for generic artifact patching behavior."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.tools.artifact_patcher import (
    normalize_spec,
    patch_controller,
    sample_value,
)
from agent.tools.scaffold_runner import build_execution_env


class ArtifactPatcherTest(unittest.TestCase):
    def test_requirement_sample_defaults_work_without_profile(self) -> None:
        model = normalize_spec(
            {
                "project": {"name": "access-operator"},
                "api": {
                    "kind": "AccessPolicy",
                    "version": "v1alpha1",
                    "group": "access",
                    "domain": "example.io",
                },
                "specFields": [
                    {"name": "ruleVerbs", "type": "[]string"}
                ],
                "statusFields": [
                    {"name": "phase", "type": "string"}
                ],
                "sampleDefaults": {"ruleVerbs": ["get"]},
            },
            {},
            None,
        )

        self.assertEqual(
            model["profile"]["sampleDefaults"],
            {"ruleVerbs": ["get"]},
        )

    def test_camel_case_string_sample_is_dns_safe(self) -> None:
        self.assertEqual(
            sample_value("string", "appName"),
            "sample-app-name",
        )

    def test_kubernetes_semantic_samples_are_executable(self) -> None:
        self.assertEqual(
            sample_value("string", "schedule"),
            "*/5 * * * *",
        )
        self.assertEqual(
            sample_value("string", "storageSize"),
            "1Gi",
        )
        self.assertEqual(
            sample_value("[]string", "accessModes"),
            ["ReadWriteOnce"],
        )
        self.assertEqual(
            sample_value("string", "namespaceName"),
            "default",
        )

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
        status = {
            item["name"]: item["type"]
            for item in model["statusFields"]
        }
        self.assertEqual(status["observedGeneration"], "int64")
        self.assertEqual(status["conditions"], "[]metav1.Condition")

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

    def test_profile_patch_rejects_remaining_scaffold_todo(self) -> None:
        model = {
            "api": {"kind": "Widget"},
            "controller": {"managedResources": ["ConfigMap"]},
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

func (r *WidgetReconciler) Reconcile() {
\t// TODO(user): your logic here
}
"""

        with self.assertRaisesRegex(
            SystemExit,
            "scaffold TODO remains",
        ):
            patch_controller(controller, model)

    def test_profile_patch_allows_implemented_reconcile_with_scaffold_docs(
        self,
    ) -> None:
        model = {
            "api": {"kind": "Widget"},
            "controller": {"managedResources": ["ConfigMap"]},
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

// TODO(user): Modify the Reconcile function to compare desired state.
func (r *WidgetReconciler) Reconcile() {
\tr.Create()
}
"""

        patched = patch_controller(controller, model)

        self.assertIn("r.Create()", patched)

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
