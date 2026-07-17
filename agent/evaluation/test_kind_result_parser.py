"""Tests for structured kind result extraction."""

from __future__ import annotations

import unittest

from agent.evaluation.kind_result_parser import parse_summary


class KindResultParserTest(unittest.TestCase):
    def test_last_lifecycle_object_is_used(self) -> None:
        summary = parse_summary(
            'progress\n{"status":"succeeded","checks":{"ok":true}}\n'
        )

        self.assertEqual(summary["status"], "succeeded")
        self.assertTrue(summary["checks"]["ok"])


if __name__ == "__main__":
    unittest.main()
