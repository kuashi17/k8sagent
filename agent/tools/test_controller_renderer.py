"""Tests for profile-less Controller rendering."""

from __future__ import annotations

import unittest

from agent.tools.controller_renderer import render_controller


def model(resources, spec_fields, status_fields):
    return {
        "project": {"module": "sample.io/example-operator"},
        "api": {
            "kind": "Example",
            "group": "apps",
            "version": "v1alpha1",
        },
        "controller": {"managedResources": resources},
        "specFields": [{"name": name} for name in spec_fields],
        "statusFields": [{"name": name} for name in status_fields],
        "rbacResources": [
            {
                "apiGroup": "apps.sample.io",
                "resource": "examples",
                "verbs": ["get", "list", "watch"],
            }
        ],
    }


class ControllerRendererTest(unittest.TestCase):
    def test_deployment_and_service_behavior_is_rendered(self) -> None:
        rendered = render_controller(
            model(
                ["Deployment", "Service"],
                ["image", "replicas", "port"],
                [
                    "phase",
                    "deploymentName",
                    "serviceName",
                    "message",
                ],
            )
        )
        self.assertIn("reconcileDeployment", rendered)
        self.assertIn("reconcileService", rendered)
        self.assertIn("CreateOrUpdate", rendered)
        self.assertIn("Status().Update", rendered)
        self.assertIn("SetControllerReference", rendered)

    def test_namespace_policy_updates_labels_without_owner_reference(self) -> None:
        rendered = render_controller(
            model(
                ["Namespace"],
                ["namespaceName", "labels"],
                ["phase", "observedNamespace", "message"],
            )
        )
        namespace_function = rendered.split(
            "func (r *ExampleReconciler) reconcileNamespace",
            1,
        )[1].split("func ", 1)[0]
        self.assertIn("object.SetLabels(labels)", namespace_function)
        self.assertIn("r.Get(", namespace_function)
        self.assertIn("r.Update(", namespace_function)
        self.assertNotIn("CreateOrUpdate", namespace_function)
        self.assertNotIn("setOwner(", namespace_function)

    def test_enabled_false_deletes_managed_secret(self) -> None:
        rendered = render_controller(
            model(
                ["Secret"],
                ["secretName", "data", "enabled"],
                ["phase", "secretName", "message"],
            )
        )
        self.assertIn("if !instance.Spec.Enabled", rendered)
        self.assertIn("r.Delete(ctx, object)", rendered)


if __name__ == "__main__":
    unittest.main()
