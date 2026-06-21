"""Tests for validated Web workflow command construction."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from web.schemas import RequirementRunRequest
from web.workflow_service import WorkflowService


class WorkflowServiceTest(unittest.TestCase):
    def test_execute_command_requires_contract_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profiles = root / "profiles"
            profiles.mkdir()
            service = WorkflowService(
                root,
                root / "logs" / "web",
                profiles,
            )
            request = RequirementRunRequest(
                requirement_text="Create a ConfigMap Operator.",
                mode="execute",
                confirm_execute=True,
            )
            command = service.build_requirement_command(
                request,
                root / "requirement.txt",
            )

        self.assertIn("--execute", command)
        self.assertIn("execute", command)

    def test_profile_path_cannot_escape_profile_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            profiles = root / "profiles"
            profiles.mkdir()
            outside = root / "outside.yaml"
            outside.write_text("profileName: outside", encoding="utf-8")
            service = WorkflowService(
                root,
                root / "logs" / "web",
                profiles,
            )

            with self.assertRaisesRegex(ValueError, "profiles"):
                service.validate_profile("outside.yaml")


if __name__ == "__main__":
    unittest.main()
