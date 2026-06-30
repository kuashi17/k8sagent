"""Tests for deterministic-first log analysis orchestration."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.log_analysis_orchestrator import call_log_planner


class LogAnalysisOrchestratorTest(unittest.TestCase):
    def test_unknown_classification_uses_short_log_analysis_timeout(self) -> None:
        analysis = {
            "status": "failed",
            "primaryClassification": {"type": "unknown"},
        }
        llm_output = {
            "decision": "failed",
            "classification": "unknown",
            "rootCause": "unknown",
            "evidence": ["stderr"],
            "recommendedFixes": ["inspect logs"],
            "rerunCommand": "",
            "explanationForBeginner": "inspect logs",
        }
        with patch(
            "agent.log_analysis_orchestrator.analyze_log_with_llm",
            return_value=(llm_output, {"mode": "log-analysis"}, "{}"),
        ) as analyze:
            result = call_log_planner({}, "", [], analysis)

        self.assertTrue(result["llmPlannerUsed"])
        config = analyze.call_args.kwargs["config"]
        self.assertEqual(config.timeout_seconds, 10)
        self.assertEqual(config.max_tokens, 240)

    def test_known_classification_skips_llm(self) -> None:
        analysis = {
            "status": "failed",
            "failedStep": "spec_generator",
            "primaryClassification": {
                "type": "incomplete-requirement",
                "cause": "필수 정보가 누락되었습니다.",
                "resolution": "요구사항을 보완합니다.",
            },
            "evidence": "Missing required field: specFields",
            "recommendedCommand": "",
        }
        with patch(
            "agent.log_analysis_orchestrator.analyze_log_with_llm",
            side_effect=AssertionError("LLM must not run"),
        ):
            result = call_log_planner({}, "", [], analysis)

        self.assertFalse(result["llmPlannerUsed"])
        self.assertTrue(result["fallbackUsed"])
        self.assertEqual(
            result["llmOutput"]["classification"],
            "incomplete-requirement",
        )
        self.assertEqual(result["error"], "")

    def test_unknown_llm_failure_keeps_deterministic_result(self) -> None:
        analysis = {
            "status": "failed",
            "failedStep": "unknown-step",
            "primaryClassification": {
                "type": "unknown",
                "cause": "확정할 수 없습니다.",
                "resolution": "stdout/stderr를 확인합니다.",
            },
            "evidence": "actual stderr evidence",
            "recommendedCommand": "",
        }
        with patch(
            "agent.log_analysis_orchestrator.analyze_log_with_llm",
            side_effect=TimeoutError("timed out"),
        ):
            result = call_log_planner({}, "", [], analysis)

        self.assertEqual(result["error"], "")
        self.assertEqual(result["llmOutput"]["rootCause"], "확정할 수 없습니다.")
        self.assertIn("actual stderr evidence", result["llmOutput"]["evidence"])


if __name__ == "__main__":
    unittest.main()
