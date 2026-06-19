"""Tests for Agent planning cache isolation."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from agent.llm_cache import requirement_plan_cache_metadata


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
