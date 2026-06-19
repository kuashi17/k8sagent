"""Tests for persistent asynchronous Web jobs."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
