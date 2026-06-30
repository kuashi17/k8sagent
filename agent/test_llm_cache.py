"""Tests for Agent planning cache isolation."""

from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.llm_cache import (
    REQUIREMENT_PLAN_CACHE_VERSION,
    read_requirement_plan_cache,
    requirement_plan_cache_metadata,
)


class LlmCacheTest(unittest.TestCase):
    def test_planning_model_changes_cache_key(self) -> None:
        payload = {"mode": "requirement-planning", "requirementText": "x"}
        with patch.dict(
            os.environ,
            {"LOCAL_LLM_PLANNING_MODEL": "planner-a"},
            clear=False,
        ):
            first = requirement_plan_cache_metadata(payload)["key"]
        with patch.dict(
            os.environ,
            {"LOCAL_LLM_PLANNING_MODEL": "planner-b"},
            clear=False,
        ):
            second = requirement_plan_cache_metadata(payload)["key"]

        self.assertNotEqual(first, second)

    def test_contract_digest_is_part_of_cache_key(self) -> None:
        payload = {"mode": "requirement-planning", "requirementText": "x"}
        with patch(
            "agent.llm_cache.planning_cache_contract",
            return_value={"digest": "contract-a", "components": {}},
        ):
            first = requirement_plan_cache_metadata(payload)["key"]
        with patch(
            "agent.llm_cache.planning_cache_contract",
            return_value={"digest": "contract-b", "components": {}},
        ):
            second = requirement_plan_cache_metadata(payload)["key"]

        self.assertNotEqual(first, second)

    def test_stale_contract_cache_entry_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache.json"
            path.write_text(
                json.dumps(
                    {
                        "cacheVersion": REQUIREMENT_PLAN_CACHE_VERSION,
                        "contractDigest": "old-contract",
                        "llmOutput": {"toolCalls": []},
                    }
                ),
                encoding="utf-8",
            )
            result = read_requirement_plan_cache(
                {
                    "path": path,
                    "contractDigest": "current-contract",
                },
                {},
            )

        self.assertIsNone(result)
