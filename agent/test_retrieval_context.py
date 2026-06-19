"""Tests for Agent retrieval context selection."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent.rag.retriever import keyword_search
from agent.retrieval_context import requirement_rag_limit, select_context


class RetrievalContextTest(unittest.TestCase):
    def test_requirement_context_balances_reference_and_few_shot(self) -> None:
        selected = select_context(
            {
                "hybridResults": [
                    {"sourcePath": "guide.md", "category": "guide"},
                    {"sourcePath": "example.md", "category": "example"},
                    {"sourcePath": "other.md", "category": "other"},
                ]
            },
            3,
            "requirement",
        )

        self.assertEqual(
            [item["sourcePath"] for item in selected],
            ["guide.md", "example.md", "other.md"],
        )
        self.assertEqual(selected[0]["contextType"], "reference")
        self.assertEqual(selected[1]["contextType"], "few-shot")

    def test_duplicate_sources_are_removed(self) -> None:
        selected = select_context(
            {
                "hybridResults": [
                    {"sourcePath": "same.md", "category": "guide"},
                    {"sourcePath": "same.md", "category": "example"},
                ]
            },
            3,
            "requirement",
        )

        self.assertEqual(len(selected), 1)

    def test_requirement_limit_is_bounded(self) -> None:
        with patch.dict(os.environ, {"AGENT_REQUIREMENT_RAG_LIMIT": "99"}):
            self.assertEqual(requirement_rag_limit(), 3)
        with patch.dict(os.environ, {"AGENT_REQUIREMENT_RAG_LIMIT": "invalid"}):
            self.assertEqual(requirement_rag_limit(), 2)

    def test_requirement_fixtures_select_domain_example(self) -> None:
        cases = {
            "SecretSync source Secret destination Secret": "knowledge-base/examples/secret-sync.md",
            "ScheduledTask CronJob schedule image": "knowledge-base/examples/scheduled-task.md",
            "WebService Deployment Service replicas": "knowledge-base/examples/web-service.md",
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                details = {"hybridResults": keyword_search(query, limit=8)}
                selected = select_context(details, 3, "requirement")
                self.assertIn(
                    expected,
                    [item.get("sourcePath") for item in selected],
                )


if __name__ == "__main__":
    unittest.main()
