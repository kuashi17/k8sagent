"""Tests for requirement-to-spec generation."""

from __future__ import annotations

import unittest

from agent.tools.spec_generator import (
    MAX_PROJECT_NAME_LENGTH,
    bounded_project_name,
    mapping_target_kind,
    parse_sample_defaults,
)


class SpecGeneratorTest(unittest.TestCase):
    def test_requirement_sample_spec_is_parsed_without_profile(self) -> None:
        warnings: list[str] = []
        values = parse_sample_defaults(
            """
샘플 Custom Resource는 다음 값을 사용한다.
apiVersion: access.sample.io/v1alpha1
kind: AccessBundle
spec:
  ruleApiGroups: [""]
  ruleResources: [serviceaccounts]
  ruleVerbs: [get]
""",
            warnings,
        )

        self.assertEqual(
            values,
            {
                "ruleApiGroups": [""],
                "ruleResources": ["serviceaccounts"],
                "ruleVerbs": ["get"],
            },
        )
        self.assertEqual(warnings, [])

    def test_unknown_managed_kind_is_inferred_from_mapping_target(self) -> None:
        self.assertEqual(
            mapping_target_kind(
                "NetworkPolicy.spec.podSelector.matchLabels"
            ),
            "NetworkPolicy",
        )

    def test_short_project_name_keeps_readable_operator_suffix(
        self,
    ) -> None:
        self.assertEqual(
            bounded_project_name("WebService"),
            "web-service-operator",
        )

    def test_long_project_name_is_dns_safe_and_stable(self) -> None:
        first = bounded_project_name("NamespaceLabelPolicy")
        second = bounded_project_name("NamespaceLabelPolicy")

        self.assertEqual(first, second)
        self.assertLessEqual(len(first), MAX_PROJECT_NAME_LENGTH)
        self.assertRegex(first, r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
        self.assertIn("-op-", first)


if __name__ == "__main__":
    unittest.main()
