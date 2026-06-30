"""Tests for persistent asynchronous Web jobs."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from web.job_manager import (
    JobManager,
    build_journey_timings,
    infer_phase,
    isolate_job_command,
)


class JobManagerTest(unittest.TestCase):
    def test_requirement_command_uses_job_specific_output_directories(self) -> None:
        command = isolate_job_command(
            "requirement",
            [
                "python3",
                "agent/langchain_agent.py",
                "--requirement",
                "requirement.txt",
                "--workspace",
                "shared-workspace",
            ],
            "logs/web/jobs/job-1",
        )

        self.assertEqual(
            command[command.index("--workspace") + 1],
            "logs/web/jobs/job-1/workspace",
        )
        self.assertEqual(
            command[command.index("--artifact-dir") + 1],
            "logs/web/jobs/job-1/artifacts",
        )
        self.assertNotIn("shared-workspace", command)

    def test_separate_requirement_jobs_never_share_mutable_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = JobManager(
                root,
                root / "jobs",
                execution_mode="external",
            )
            base = [
                "python3",
                "agent/langchain_agent.py",
                "--requirement",
                "requirement.txt",
            ]

            first = manager.submit("requirement", base)
            second = manager.submit("requirement", base)

            self.assertNotEqual(first["jobId"], second["jobId"])
            self.assertNotEqual(
                first["command"][first["command"].index("--workspace") + 1],
                second["command"][second["command"].index("--workspace") + 1],
            )
            self.assertNotEqual(
                first["command"][first["command"].index("--artifact-dir") + 1],
                second["command"][second["command"].index("--artifact-dir") + 1],
            )

    def test_linked_approval_journey_separates_human_wait(self) -> None:
        timings = build_journey_timings(
            {
                "state": "succeeded",
                "createdAt": "2026-06-28T00:00:25+00:00",
                "startedAt": "2026-06-28T00:00:26+00:00",
                "finishedAt": "2026-06-28T00:00:45+00:00",
            },
            {"timings": {"totalSeconds": 18}},
            {
                "jobId": "plan-1",
                "createdAt": "2026-06-28T00:00:00+00:00",
                "startedAt": "2026-06-28T00:00:01+00:00",
                "finishedAt": "2026-06-28T00:00:05+00:00",
            },
            {"timings": {"totalSeconds": 3}},
        )

        self.assertEqual(timings["approvalWaitingSeconds"], 20)
        self.assertEqual(timings["automationSeconds"], 23)
        self.assertEqual(timings["totalJourneySeconds"], 45)
        self.assertEqual(timings["approvalParentJobId"], "plan-1")

    def test_job_runs_in_background_and_persists_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = JobManager(root, root / "jobs")
            job = manager.submit(
                "test",
                [
                    "python3",
                    "-c",
                    "import time; print('LLM Agent Orchestrator', flush=True); time.sleep(0.1); print('Agent logs: logs/agent/test', flush=True)",
                ],
            )

            self.assertIn(manager.get(job["jobId"])["state"], {"queued", "running", "succeeded"})
            deadline = time.time() + 5
            result = None
            while time.time() < deadline:
                result = manager.result(job["jobId"])
                if result and result["state"] in {"succeeded", "failed"}:
                    break
                time.sleep(0.05)

            self.assertIsNotNone(result)
            self.assertEqual(result["state"], "succeeded")
            self.assertEqual(result["agentLogDir"], "logs/agent/test")
            self.assertIn("LLM Agent Orchestrator", result["stdoutTail"])
            self.assertTrue((root / "jobs" / job["jobId"] / "status.json").is_file())
            self.assertTrue(result["journeyTimings"]["terminal"])
            self.assertGreaterEqual(
                result["journeyTimings"]["totalJourneySeconds"],
                result["journeyTimings"]["executionSeconds"],
            )

    def test_phase_inference_uses_latest_workflow_marker_priority(self) -> None:
        stdout = "LLM Agent Orchestrator\nCalling tool: spec_generator\nCalling tool: validation\n"
        self.assertEqual(infer_phase(stdout, "running"), "validation")

    def test_cancel_terminates_running_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = JobManager(root, root / "jobs")
            job = manager.submit(
                "test",
                ["python3", "-c", "import time; time.sleep(30)"],
            )
            deadline = time.time() + 5
            while time.time() < deadline:
                if manager.get(job["jobId"])["state"] == "running":
                    break
                time.sleep(0.02)
            canceled = manager.cancel(job["jobId"])
            self.assertEqual(canceled["state"], "canceled")

    def test_restart_marks_running_job_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            job_dir = root / "jobs" / "old-job"
            job_dir.mkdir(parents=True)
            (job_dir / "status.json").write_text(
                json.dumps({"jobId": "old-job", "state": "running"}),
                encoding="utf-8",
            )
            manager = JobManager(root, root / "jobs")
            self.assertEqual(manager.get("old-job")["state"], "interrupted")

    def test_external_workers_claim_a_job_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = JobManager(
                root,
                root / "jobs",
                execution_mode="external",
            )
            submitted = manager.submit("test", ["python3", "-c", "print('ok')"])

            first = manager.claim_next("worker-1")
            second = manager.claim_next("worker-2")

            self.assertEqual(first["jobId"], submitted["jobId"])
            self.assertIsNone(second)

    def test_failed_external_job_can_be_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = JobManager(
                root,
                root / "jobs",
                execution_mode="external",
            )
            submitted = manager.submit("test", ["python3", "-c", "raise SystemExit(1)"])
            job_dir = root / "jobs" / submitted["jobId"]
            status = manager.get(submitted["jobId"])
            status["state"] = "failed"
            manager._write_status(job_dir, status)

            retried = manager.retry(submitted["jobId"])

            self.assertEqual(retried["attempt"], 2)
            self.assertEqual(retried["state"], "queued")


if __name__ == "__main__":
    unittest.main()
