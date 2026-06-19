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
)


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

    def test_extracts_only_well_formed_planner_collections(self) -> None:
        data = {"reasoning": ["one"], "toolCalls": [{"tool": "validation"}, "bad"]}
        self.assertEqual(extract_list(data, "reasoning"), ["one"])
        self.assertEqual(extract_tool_call_plan(data), [{"tool": "validation"}])


if __name__ == "__main__":
    unittest.main()
