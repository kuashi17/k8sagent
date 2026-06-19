"""Tests for persistent asynchronous Web jobs."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from web.job_manager import JobManager, infer_phase


class JobManagerTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
