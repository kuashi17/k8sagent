"""Tests for isolated Operator compile orchestration."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.evaluation.compile_matrix_runner import run_step


class CompileMatrixRunnerTest(unittest.TestCase):
    @patch("agent.evaluation.compile_matrix_runner.subprocess.run")
    def test_run_step_adds_stable_go_environment(self, run) -> None:
        run.return_value.returncode = 0
        run.return_value.stdout = "ok"
        run.return_value.stderr = ""

        result = run_step("validation", ["make", "test"])

        env = run.call_args.kwargs["env"]
        self.assertIn("-buildvcs=false", env["GOFLAGS"])
        self.assertIn(".tools/bin", env["PATH"])
        self.assertEqual(result["status"], "succeeded")


if __name__ == "__main__":
    unittest.main()
