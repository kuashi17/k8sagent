"""Tests for the pre-Tool clarification gate."""

from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.requirement_orchestrator import run_requirement_agent


class RequirementClarificationTest(unittest.TestCase):
    def test_ambiguous_types_stop_without_artifacts_or_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            requirement = root / "requirement.txt"
            requirement.write_text(
                """
InvalidExample Operator를 생성한다.
API는 invalid.sample.io/v1alpha1이다.
spec:
count: 숫자 타입
options: 알 수 없는 사용자 정의 타입
status:
phase: string
Controller는 Deployment를 생성한다.
""",
                encoding="utf-8",
            )
            log_dir = root / "logs"
            log_dir.mkdir()
            artifact_dir = root / "artifacts"
            workspace = root / "workspace"
            args = argparse.Namespace(
                requirement=str(requirement),
                workspace=str(workspace),
                artifact_dir=str(artifact_dir),
                resume_existing=False,
                capability_proposal="",
                capability_approval="",
                mode="dry-run",
                execute=False,
                run_level="fast",
                skip_final_llm_evaluation=False,
                no_cache=True,
                refresh_cache=False,
            )
            with (
                patch(
                    "agent.requirement_orchestrator.make_agent_log_dir",
                    return_value=log_dir,
                ),
                patch(
                    "agent.requirement_orchestrator.perform_retrieval",
                    return_value={"selectedContext": [], "retrievalMode": "test"},
                ),
                patch(
                    "agent.requirement_orchestrator.call_requirement_planner",
                    side_effect=AssertionError("LLM must not run"),
                ),
                patch(
                    "agent.requirement_orchestrator.execute_planned_tools",
                    side_effect=AssertionError("Tools must not run"),
                ),
            ):
                exit_code = run_requirement_agent(args)
            summary = json.loads(
                (log_dir / "summary.json").read_text(encoding="utf-8")
            )

            self.assertEqual(exit_code, 0)
            self.assertEqual(
                summary["clarificationContext"]["errorCode"],
                "INVALID_FIELD_TYPE",
            )
            self.assertEqual(summary["toolResults"], [])
            self.assertEqual(summary["generatedFiles"], {})
            self.assertEqual(summary["failureContext"], {})
            self.assertFalse(summary["recovery"]["waitingForUserApproval"])
            self.assertEqual(summary["recovery"]["plan"], {})
            self.assertFalse(artifact_dir.exists())
            self.assertFalse(workspace.exists())
            self.assertNotIn(
                "undefined: notatype",
                json.dumps(summary, ensure_ascii=False),
            )

    def test_missing_kind_skips_llm_and_all_tools(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            requirement = root / "requirement.txt"
            requirement.write_text(
                """
이미지와 replicas 값을 받아 Deployment를 생성하는 Operator를 만들고 싶습니다.
API는 apps.sample.io/v1alpha1을 사용합니다.
status에서는 준비된 replicas 수와 처리 결과를 보고 싶습니다.
""",
                encoding="utf-8",
            )
            log_dir = root / "logs"
            log_dir.mkdir()
            args = argparse.Namespace(
                requirement=str(requirement),
                workspace=str(root / "workspace"),
                kind_deploy=False,
                resume_existing=False,
                capability_proposal="",
                capability_approval="",
                mode="dry-run",
                execute=False,
                run_level="fast",
                skip_final_llm_evaluation=False,
                no_cache=True,
                refresh_cache=False,
            )
            with (
                patch(
                    "agent.requirement_orchestrator.make_agent_log_dir",
                    return_value=log_dir,
                ),
                patch(
                    "agent.requirement_orchestrator.perform_retrieval",
                    return_value={
                        "selectedContext": [],
                        "retrievalMode": "test",
                    },
                ),
                patch(
                    "agent.requirement_orchestrator.call_requirement_planner",
                    side_effect=AssertionError("LLM must not run"),
                ),
                patch(
                    "agent.requirement_orchestrator.execute_planned_tools",
                    side_effect=AssertionError("Tools must not run"),
                ),
            ):
                exit_code = run_requirement_agent(args)

            summary = json.loads(
                (log_dir / "summary.json").read_text(encoding="utf-8")
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(summary["runStatus"], "clarification-required")
        self.assertEqual(summary["missingInformation"], ["kind"])
        self.assertEqual(summary["toolResults"], [])
        self.assertFalse(summary["agentResult"]["canExecute"])
        self.assertIn(
            "Custom Resource 이름",
            summary["clarifyingQuestions"][0],
        )
        self.assertEqual(
            summary["safetyEvaluation"]["llmProviderPolicy"]["status"],
            "not-needed",
        )


if __name__ == "__main__":
    unittest.main()
