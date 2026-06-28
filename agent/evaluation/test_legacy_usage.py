"""Tests for the legacy path budget."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.evaluation.legacy_usage import measure_legacy_usage


class LegacyUsageTest(unittest.TestCase):
    def test_rejects_reference_outside_approved_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "allowed.py").write_text("old-adapter", encoding="utf-8")
            (root / "new.py").write_text("old-adapter", encoding="utf-8")
            policy = root / "policy.yaml"
            policy.write_text(
                """
paths:
  - id: old
    patterns: [old-adapter]
    allowedPaths: [allowed.py]
""",
                encoding="utf-8",
            )

            result = measure_legacy_usage(root, policy)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["violations"][0]["path"], "new.py")
