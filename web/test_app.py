"""FastAPI routing tests for asynchronous Web workflow submission."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ["LOCAL_LLM_WARMUP"] = "false"

from httpx import ASGITransport, AsyncClient  # noqa: E402

from web.app import app  # noqa: E402


class FakeJobs:
    def submit(self, job_type, command, **kwargs):
        return {"jobId": "20260619-async0001", "jobType": job_type, "command": command}

    def result(self, job_id):
        if job_id != "20260619-async0001":
            return None
        return {
            "jobId": job_id,
            "state": "running",
            "phase": "LLM planning",
            "commandText": "python3 agent/langchain_agent.py",
            "metadata": {},
            "stdoutTail": "LLM Agent Orchestrator",
            "stderrTail": "",
            "agentLogDir": "",
            "startedAt": "2026-06-19T00:00:00+09:00",
        }

    def list(self, limit=20):
        return []

    def cancel(self, job_id):
        job = self.result(job_id)
        if job:
            job.update({"state": "canceled", "phase": "canceled"})
        return job

    def retry(self, job_id):
        job = self.result(job_id)
        if job:
            job.update(
                {
                    "jobId": "20260619-retry0001",
                    "state": "queued",
                    "attempt": 2,
                }
            )
        return job


class FakeCompletedJobs(FakeJobs):
    def result(self, job_id):
        if job_id != "20260619-async0001":
            return None
        return {
            "jobId": job_id,
            "jobType": "requirement",
            "state": "succeeded",
            "phase": "completed",
            "commandText": "python3 agent/langchain_agent.py",
            "metadata": {
                "requirementPath": "",
                "profile": "",
                "mode": "dry-run",
                "runLevel": "fast",
            },
            "stdoutTail": "",
            "stderrTail": "",
            "agentLogDir": "logs/agent/example",
            "startedAt": "2026-06-19T00:00:00+09:00",
            "attempt": 1,
            "maxAttempts": 2,
            "rollbackPolicy": {"mode": "not-applicable"},
            "summary": {
                "agentMode": "dry-run",
                "requirementSummary": {
                    "kind": "WebService",
                    "managedResources": ["Deployment", "Service"],
                    "shortSummary": "웹 서비스를 배포합니다.",
                },
                "toolResults": [
                    {"tool": "spec_generator", "exitCode": 0}
                ],
                "generatedFiles": {
                    "operatorSpec": "generated/webservice.yaml"
                },
                "warnings": [],
                "errors": [],
                "nextRecommendedActions": ["계획을 검토합니다."],
                "finalLLM": {"output": {}},
            },
            "agentReport": "",
            "evidence": {},
            "safety": {},
            "recovery": {},
        }

    def list(self, limit=20):
        return [
            {
                "jobId": "20260619-async0001",
                "jobType": "requirement",
                "state": "failed",
                "createdAt": "2026-06-19T00:00:00+09:00",
                "agentLogDir": "logs/agent/example",
            }
        ]


class AsyncWebRouteTest(unittest.IsolatedAsyncioTestCase):
    async def request(self, method, path, **kwargs):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, **kwargs)

    async def test_requirement_submission_redirects_to_job_immediately(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "POST",
                "/run-requirement",
                data={
                    "requirement_text": "Create an Operator.",
                    "mode": "dry-run",
                    "run_level": "fast",
                },
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/runs/job/20260619-async0001")

    async def test_job_status_endpoint_exposes_progress(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "GET",
                "/api/jobs/20260619-async0001",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phase"], "LLM planning")
        self.assertFalse(response.json()["terminal"])

    async def test_health_endpoint_exposes_queue_status(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request("GET", "/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["service"], "kubebuilder-agent-web")
        self.assertEqual(response.json()["jobs"]["queued"], 0)

    async def test_job_can_be_canceled(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "POST",
                "/api/jobs/20260619-async0001/cancel",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "canceled")

    async def test_failed_job_can_be_retried(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "POST",
                "/api/jobs/20260619-async0001/retry",
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["attempt"], 2)

    async def test_home_hides_advanced_options_by_default(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request("GET", "/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("안전한 계획 만들기", response.text)
        self.assertIn("<summary>개발자 설정</summary>", response.text)
        self.assertIn("막막하다면 예시로 시작하세요", response.text)
        self.assertIn(">웹 서비스</button>", response.text)
        self.assertNotIn("TrainingJob", response.text)
        self.assertNotIn("requirements/appconfig.txt", response.text)
        self.assertNotIn("계획 확인 없이 바로 실행", response.text)
        self.assertNotIn("기존 프로젝트에서 계속", response.text)
        self.assertNotIn("Safety Evaluation</summary>", response.text)

    async def test_log_analysis_selects_recent_failed_job(self) -> None:
        with patch("web.app.jobs", FakeCompletedJobs()):
            response = await self.request("GET", "/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("선택한 로그 분석", response.text)
        self.assertIn(
            'value="logs/agent/example" selected',
            response.text,
        )

    async def test_empty_log_analysis_shows_inline_error(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "POST",
                "/analyze-log",
                data={"log_dir": ""},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("분석할 로그 작업을 먼저 선택", response.text)
        self.assertIn('<details class="support-tools" open>', response.text)

    async def test_short_requirement_is_rejected_for_beginner(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "POST",
                "/run-requirement",
                data={"requirement_text": "짧음"},
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("조금 더 자세히", response.text)

    async def test_execute_requires_explicit_confirmation(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "POST",
                "/run-requirement",
                data={
                    "requirement_text": "ConfigMap을 생성하는 Operator를 만들어 주세요.",
                    "mode": "execute",
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("실행 승인", response.text)

    async def test_kind_deploy_requires_profile(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "POST",
                "/run-requirement",
                data={
                    "requirement_text": "ConfigMap을 생성하는 Operator를 만들어 주세요.",
                    "kind_deploy": "on",
                },
            )

        self.assertEqual(response.status_code, 422)
        self.assertIn("Profile", response.text)

    async def test_completed_plan_shows_beginner_execution_action(self) -> None:
        with patch("web.app.jobs", FakeCompletedJobs()):
            response = await self.request(
                "GET",
                "/runs/job/20260619-async0001",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn("WebService 계획이 준비됐습니다", response.text)
        self.assertIn("이 계획대로 만들기", response.text)
        self.assertIn("아직 실제 파일이나 클러스터를 변경하지 않았습니다", response.text)
        self.assertIn("개발자용 실행 근거와 원본 로그", response.text)

    async def test_running_job_uses_beginner_facing_status_labels(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            response = await self.request(
                "GET",
                "/runs/job/20260619-async0001",
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn(">진행 중</span>", response.text)
        self.assertIn("요구사항 분석과 계획 생성", response.text)
        self.assertNotIn(">LLM planning</strong>", response.text)


if __name__ == "__main__":
    unittest.main()
