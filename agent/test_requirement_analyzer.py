"""Tests for requirement intent and managed-resource inference."""

from __future__ import annotations

import unittest

from agent.requirement_analyzer import (
    analyze_requirement_intent,
    infer_managed_resources,
)


class RequirementAnalyzerTest(unittest.TestCase):
    def test_operator_requirement_is_classified(self) -> None:
        result = analyze_requirement_intent(
            "WebApp Operator를 만들고 Controller는 Deployment를 관리합니다."
        )

        self.assertEqual(result["primaryIntent"], "operator_generation")
        self.assertIn("Deployment", result["managedResourceHints"])

    def test_pvc_alias_is_normalized(self) -> None:
        resources = infer_managed_resources(
            "Controller는 PVC를 생성하고 관리합니다."
        )

        self.assertEqual(resources, ["PersistentVolumeClaim"])


if __name__ == "__main__":
    unittest.main()
