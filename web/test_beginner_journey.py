"""End-to-end contract test for the beginner Web journey."""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient

from web.app import app
from web.job_manager import JobManager
from web.workflow_service import WorkflowService


FAKE_AGENT = r'''#!/usr/bin/env python3
import json
import sys
from pathlib import Path

mode = sys.argv[sys.argv.index("--mode") + 1]
log_dir = Path("logs") / "agent" / f"journey-{mode}"
log_dir.mkdir(parents=True, exist_ok=True)
tools = ["spec_generator", "command_planner"]
if mode == "execute":
    tools.extend(["scaffold_runner", "artifact_patcher", "validation"])
summary = {
    "agentMode": mode,
    "requirementSummary": {
        "kind": "GenericController",
        "managedResources": ["ConfigMap"],
        "shortSummary": "입력한 설정을 관리하는 Operator입니다.",
    },
    "toolResults": [
        {"tool": tool, "exitCode": 0, "status": "succeeded"}
        for tool in tools
    ],
    "generatedFiles": {
        "operatorSpec": "generated/generic-controller-spec.yaml"
    },
    "warnings": [],
    "errors": [],
    "nextRecommendedActions": [
        "계획을 승인합니다." if mode == "dry-run" else "생성 결과를 확인합니다."
    ],
    "finalLLM": {
        "output": {"beginnerSummary": "안전한 작업 흐름을 완료했습니다."}
    },
}
(log_dir / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False), encoding="utf-8"
)
(log_dir / "safety-evaluation.json").write_text(
    json.dumps({"status": "passed"}), encoding="utf-8"
)
(log_dir / "evidence-trace.json").write_text(
    json.dumps({"status": "complete"}), encoding="utf-8"
)
print("LLM Agent Orchestrator", flush=True)
for tool in tools:
    print(f"Calling tool: {tool}", flush=True)
print(f"Agent logs: {log_dir}", flush=True)
'''


class BeginnerJourneyTest(unittest.IsolatedAsyncioTestCase):
    async def test_plan_review_execute_and_result_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "agent").mkdir()
            (root / "profiles").mkdir()
            agent = root / "agent" / "langchain_agent.py"
            agent.write_text(textwrap.dedent(FAKE_AGENT), encoding="utf-8")
            manager = JobManager(
                root,
                root / "logs" / "web" / "jobs",
                execution_mode="external",
            )
            workflows = WorkflowService(
                root,
                root / "logs" / "web",
                root / "profiles",
            )
            requirement = (
                "설정 데이터를 입력받아 ConfigMap을 관리하고 상태를 표시해 주세요."
            )

            with patch("web.app.jobs", manager), patch(
                "web.app.workflows", workflows
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://testserver",
                ) as client:
                    plan_response = await client.post(
                        "/run-requirement",
                        data={
                            "requirement_text": requirement,
                            "mode": "dry-run",
                            "run_level": "fast",
                        },
                        follow_redirects=False,
                    )
                    self.assertEqual(plan_response.status_code, 303)
                    plan_job = manager.claim_next("journey-worker")
                    self.assertIsNotNone(plan_job)
                    manager.run_claimed(plan_job)

                    plan_page = await client.get(
                        plan_response.headers["location"]
                    )
                    self.assertEqual(plan_page.status_code, 200)
                    self.assertIn(
                        "GenericController 계획이 준비됐습니다",
                        plan_page.text,
                    )
                    self.assertIn(
                        "아직 실제 파일이나 클러스터를 변경하지 않았습니다",
                        plan_page.text,
                    )
                    self.assertIn("이 계획대로 만들기", plan_page.text)

                    execute_response = await client.post(
                        "/run-requirement",
                        data={
                            "requirement_text": requirement,
                            "mode": "execute",
                            "run_level": "fast",
                            "confirm_execute": "on",
                        },
                        follow_redirects=False,
                    )
                    self.assertEqual(execute_response.status_code, 303)
                    execute_job = manager.claim_next("journey-worker")
                    self.assertIsNotNone(execute_job)
                    manager.run_claimed(execute_job)

                    result_page = await client.get(
                        execute_response.headers["location"]
                    )
                    self.assertEqual(result_page.status_code, 200)
                    self.assertIn(
                        "GenericController 작업이 완료됐습니다",
                        result_page.text,
                    )
                    self.assertIn("코드 및 테스트 검증", result_page.text)
                    self.assertNotIn("이 계획대로 만들기", result_page.text)

                    requirements = list(
                        (root / "logs" / "web" / "requirement").glob(
                            "*/requirement.txt"
                        )
                    )
                    self.assertEqual(len(requirements), 2)
                    self.assertTrue(all(
                        path.read_text(encoding="utf-8") == requirement
                        for path in requirements
                    ))


if __name__ == "__main__":
    unittest.main()
