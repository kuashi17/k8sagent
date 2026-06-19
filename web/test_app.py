"""FastAPI routing tests for asynchronous Web workflow submission."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ["LOCAL_LLM_WARMUP"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

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


class AsyncWebRouteTest(unittest.TestCase):
    def test_requirement_submission_redirects_to_job_immediately(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            with TestClient(app) as client:
                response = client.post(
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

    def test_job_status_endpoint_exposes_progress(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            with TestClient(app) as client:
                response = client.get("/api/jobs/20260619-async0001")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["phase"], "LLM planning")
        self.assertFalse(response.json()["terminal"])

    def test_job_can_be_canceled(self) -> None:
        with patch("web.app.jobs", FakeJobs()):
            with TestClient(app) as client:
                response = client.post("/api/jobs/20260619-async0001/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "canceled")


if __name__ == "__main__":
    unittest.main()
