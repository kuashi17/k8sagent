"""Regression guards for generalized generation boundaries."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.tools.controller_renderer import render_controller
from agent.tools.resource_catalog import load_resource_catalog


REPO_ROOT = Path(__file__).resolve().parents[2]


class GeneralizationBoundaryTest(unittest.TestCase):
    def test_renderer_contains_no_resource_specific_dispatch(self) -> None:
        source = (
            REPO_ROOT
            / "agent"
            / "tools"
            / "controller_renderer.py"
        ).read_text(encoding="utf-8")
        forbidden = (
            '"ConfigMap"',
            '"Secret"',
            '"PersistentVolumeClaim"',
            '"CronJob"',
            '"Deployment"',
            '"StatefulSet"',
            '"Service"',
            '"Namespace"',
            "resource.kind ==",
            "resource.kind !=",
        )
        for value in forbidden:
            self.assertNotIn(value, source)

    def test_matrix_cases_live_in_fixture_not_runner(self) -> None:
        runner = (
            REPO_ROOT
            / "agent"
            / "evaluation"
            / "profileless_kind_runner.py"
        ).read_text(encoding="utf-8")
        for value in (
            "WebService",
            "SecretSync",
            "ScheduledTask",
            "NamespaceLabelPolicy",
        ):
            self.assertNotIn(value, runner)

    def test_mutation_renderer_has_no_emitter_dispatch_table(self) -> None:
        source = (
            REPO_ROOT / "agent" / "tools" / "controller_emitters.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("EMITTERS", source)
        self.assertNotIn("emit_string_map", source)
        self.assertNotIn("emit_storage_claim", source)
        self.assertNotIn("emit_stateful_workload", source)
        self.assertNotIn("emit_label_patch", source)

    def test_unseen_custom_kind_uses_existing_capabilities(
        self,
    ) -> None:
        rendered = render_controller(
            {
                "project": {
                    "module": "sample.io/queue-worker-operator"
                },
                "api": {
                    "kind": "QueueWorker",
                    "group": "workloads",
                    "version": "v1alpha1",
                },
                "controller": {
                    "managedResources": [
                        "Deployment",
                        "Service",
                    ]
                },
                "specFields": [
                    {"name": "image"},
                    {"name": "replicas"},
                    {"name": "port"},
                ],
                "statusFields": [{"name": "phase"}],
                "rbacResources": [],
            }
        )

        self.assertIn("type QueueWorkerReconciler", rendered)
        self.assertIn("reconcileDeployment", rendered)
        self.assertIn("reconcileService", rendered)

    def test_catalog_only_resource_uses_generic_nested_emitter(
        self,
    ) -> None:
        rendered = render_controller(
            {
                "project": {
                    "module": "sample.io/node-sidecar-operator"
                },
                "api": {
                    "kind": "NodeSidecar",
                    "group": "workloads",
                    "version": "v1alpha1",
                },
                "controller": {
                    "managedResources": ["DaemonSet"]
                },
                "specFields": [
                    {"name": "image"},
                    {"name": "port"},
                ],
                "statusFields": [
                    {"name": "phase"},
                    {"name": "readyReplicas", "type": "int32"},
                ],
                "rbacResources": [],
            }
        )

        self.assertIn("reconcileDaemonSet", rendered)
        self.assertIn("setNestedValue(object.Object", rendered)
        self.assertIn(
            '[]interface{}{"spec", "template", "spec", "containers", 0, "image"}',
            rendered,
        )
        self.assertIn("int64(instance.Spec.Port)", rendered)

    def test_generic_resource_without_labels_has_no_unused_variable(
        self,
    ) -> None:
        rendered = render_controller(
            {
                "project": {
                    "module": "sample.io/timer-operator"
                },
                "api": {
                    "kind": "Timer",
                    "group": "batch",
                    "version": "v1alpha1",
                },
                "controller": {
                    "managedResources": ["CronJob"]
                },
                "specFields": [
                    {"name": "schedule"},
                    {"name": "image"},
                    {"name": "command"},
                    {"name": "suspend"},
                ],
                "statusFields": [{"name": "phase"}],
                "rbacResources": [],
            }
        )
        cron_function = rendered.split(
            "func (r *TimerReconciler) reconcileCronJob",
            1,
        )[1].split("func ", 1)[0]

        self.assertNotIn("nestedLabels :=", cron_function)

    def test_every_behavior_binding_renders_without_kind_dispatch(
        self,
    ) -> None:
        catalog = load_resource_catalog()
        primitives = catalog.primitives_by_name()
        for resource in catalog.resources:
            for binding in resource.behaviorBindings:
                primitive = primitives[binding.primitive]
                with self.subTest(
                    resource=resource.kind,
                    primitive=primitive.name,
                ):
                    rendered = render_controller(
                        {
                            "project": {
                                "module": "sample.io/boundary-operator"
                            },
                            "api": {
                                "kind": "BoundaryPolicy",
                                "group": "boundary",
                                "version": "v1alpha1",
                            },
                            "controller": {
                                "managedResources": [resource.kind]
                            },
                            "specFields": [
                                {"name": field}
                                for field in primitive.activationFields
                            ],
                            "statusFields": [{"name": "phase"}],
                            "rbacResources": [],
                        }
                    )

                    self.assertIn(
                        f"reconcile{resource.kind}",
                        rendered,
                    )
                    for mutation in primitive.mutations:
                        target = mutation.target.format(**binding.paths)
                        self.assertIn(
                            target.split(".")[0],
                            rendered,
                        )


if __name__ == "__main__":
    unittest.main()
