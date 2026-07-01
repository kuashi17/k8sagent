import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.evaluation.profileless_requirement_runner import run_requirement


class ProfilelessRequirementRunnerTest(unittest.TestCase):
    def test_each_requirement_uses_output_scoped_artifacts_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            with patch(
                "agent.evaluation.profileless_requirement_runner.subprocess.run"
            ) as run:
                run.return_value.returncode = 1
                run.return_value.stdout = ""
                run.return_value.stderr = ""

                result = run_requirement(
                    "requirements/example.txt",
                    "fast",
                    "dry-run",
                    output_dir,
                    3,
                )

            command = run.call_args.args[0]
            expected_root = output_dir / "runs" / "03"
            self.assertEqual(
                command[command.index("--artifact-dir") + 1],
                str(expected_root / "artifacts"),
            )
            self.assertEqual(
                command[command.index("--workspace") + 1],
                str(expected_root / "workspace"),
            )
            self.assertEqual(result["artifactDir"], str(expected_root / "artifacts"))
            self.assertEqual(result["workspace"], str(expected_root / "workspace"))


if __name__ == "__main__":
    unittest.main()
