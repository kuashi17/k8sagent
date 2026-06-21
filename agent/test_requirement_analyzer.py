"""Tests for requirement intent and profile selection policy."""

from __future__ import annotations

import unittest

from agent.requirement_analyzer import select_profile_hint


class RequirementAnalyzerTest(unittest.TestCase):
    def test_disabled_auto_hint_does_not_discover_profiles(
        self,
    ) -> None:
        result = select_profile_hint(
            "RedisCache가 StatefulSet과 Service를 관리한다.",
            None,
            {},
            allow_auto_hint=False,
        )

        self.assertEqual(
            result["selectedProfile"]["selectionMode"],
            "disabled",
        )
        self.assertEqual(result["selectedProfile"]["path"], "")
        self.assertEqual(result["profileCandidates"], [])

    def test_explicit_profile_still_requires_enabled_policy(self) -> None:
        result = select_profile_hint(
            "TrainingJob Operator",
            "profiles/trainingjob.yaml",
            {"profileName": "trainingjob"},
            allow_auto_hint=True,
        )

        self.assertEqual(
            result["selectedProfile"]["selectionMode"],
            "explicit-hint",
        )


if __name__ == "__main__":
    unittest.main()
