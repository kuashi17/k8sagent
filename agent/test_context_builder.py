"""Tests for requirement context parsing and assembly."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.context_builder import (
    build_requirement_context,
    extract_list,
    extract_tool_call_plan,
    missing_information,
    summarize_requirement,
    target_project_dir,
)
from agent.requirement_orchestrator import reconcile_plan_with_context


REQUIREMENT = """\
WebService라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다.
domain은 sample.io, group은 apps, version은 v1alpha1, kind는 WebService로 한다.

spec에는 다음 필드를 포함한다.
- image:string
- replicas:int32

status에는 다음 필드를 포함한다.
- phase:string

Controller는 Deployment와 Service를 관리한다.
검증 명령은 make generate, make manifests, make test를 사용한다.
"""


class ContextBuilderTest(unittest.TestCase):
    def test_parses_generic_requirement(self) -> None:
        summary = summarize_requirement(REQUIREMENT)
        self.assertEqual(summary["kind"], "WebService")
        self.assertEqual(summary["specFields"], ["image", "replicas"])
        self.assertEqual(summary["managedResources"], ["Deployment", "Service"])
        self.assertEqual(missing_information(summary, REQUIREMENT), [])

    def test_assembles_retrieval_and_generated_paths(self) -> None:
        def retrieve(query: str, limit: int, purpose: str):
            self.assertEqual(purpose, "requirement")
            return {"selectedContext": [{"path": "guide.md"}], "retrievalMode": "test"}

        context = build_requirement_context(
            Path("requirements/web-service.txt"),
            REQUIREMENT,
            None,
            {},
            "workspace/generated-operators",
            retrieve,
            2,
        )
        self.assertEqual(context["generatedFiles"]["operatorSpec"], "generated/webservice-operator-spec.yaml")
        self.assertTrue(context["targetProjectDir"].endswith("web-service-operator"))
        self.assertEqual(context["retrievedKnowledge"][0]["path"], "guide.md")

    def test_parses_inline_trainingjob_fields(self) -> None:
        text = Path("requirements/trainingjob.txt").read_text(
            encoding="utf-8"
        )

        summary = summarize_requirement(text)

        self.assertEqual(
            summary["specFields"],
            [
                "image",
                "gpuCount",
                "pvcName",
                "datasetPath",
                "outputPath",
            ],
        )
        self.assertEqual(
            summary["statusFields"],
            ["phase", "jobName", "podName", "message"],
        )
        self.assertEqual(missing_information(summary, text), [])

    def test_profile_kind_project_overrides_inferred_directory(self) -> None:
        target = target_project_dir(
            "workspace/generated-operators",
            "TrainingJob",
            "trainingjob",
            {
                "kindDeployment": {
                    "project": (
                        "workspace/generated-operators/"
                        "trainingjob-operator"
                    )
                }
            },
        )

        self.assertEqual(
            target,
            "workspace/generated-operators/trainingjob-operator",
        )

    def test_profileless_context_disables_automatic_profile_selection(
        self,
    ) -> None:
        context = build_requirement_context(
            Path("requirements/web-service.txt"),
            REQUIREMENT,
            None,
            {},
            "workspace/generated-operators",
            lambda query, limit, purpose: {"selectedContext": []},
            2,
            allow_profile_hints=False,
        )

        self.assertEqual(
            context["selectedProfile"]["selectionMode"],
            "disabled",
        )
        self.assertEqual(context["selectedProfile"]["path"], "")
        self.assertTrue(
            context["targetProjectDir"].endswith(
                "web-service-operator"
            )
        )

    def test_extracts_only_well_formed_planner_collections(self) -> None:
        data = {"reasoning": ["one"], "toolCalls": [{"tool": "validation"}, "bad"]}
        self.assertEqual(extract_list(data, "reasoning"), ["one"])
        self.assertEqual(extract_tool_call_plan(data), [{"tool": "validation"}])

    def test_complete_context_removes_false_llm_missing_fields(self) -> None:
        plan = reconcile_plan_with_context(
            {
                "missingInformation": ["spec.image"],
                "risks": ["Missing spec.image", "Docker may be unavailable"],
                "nextActions": ["Define spec.image"],
            },
            {"missingInformation": []},
        )

        self.assertEqual(plan["missingInformation"], [])
        self.assertEqual(plan["risks"], ["Docker may be unavailable"])
        self.assertEqual(
            plan["nextActions"],
            ["Review generated artifacts and validated Tool evidence."],
        )


if __name__ == "__main__":
    unittest.main()
