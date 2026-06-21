"""Tests for requirement-to-spec generation."""

from __future__ import annotations

import unittest

from agent.tools.spec_generator import (
    MAX_PROJECT_NAME_LENGTH,
    bounded_project_name,
)


class SpecGeneratorTest(unittest.TestCase):
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
