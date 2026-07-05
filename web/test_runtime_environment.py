"""Tests for Docker CLI selection used by Web workers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web.runtime_environment import configure_docker_cli


class RuntimeEnvironmentTest(unittest.TestCase):
    def test_existing_working_docker_is_preserved(self) -> None:
        env = {"PATH": "/usr/bin"}
        with patch(
            "web.runtime_environment.shutil.which",
            return_value="/usr/bin/docker",
        ), patch(
            "web.runtime_environment.docker_responds",
            return_value=True,
        ):
            result = configure_docker_cli(env)

        self.assertFalse(result["configured"])
        self.assertEqual(result["source"], "existing-path")
        self.assertEqual(env["PATH"], "/usr/bin")

    def test_wsl_socket_failure_uses_working_desktop_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            desktop = root / "docker.exe"
            desktop.touch()
            env = {
                "PATH": "/usr/bin",
                "K8SAGENT_DOCKER_CLI": str(desktop),
            }

            def responds(path: Path, _env) -> bool:
                return path == desktop

            with patch(
                "web.runtime_environment.shutil.which",
                return_value="/usr/bin/docker",
            ), patch(
                "web.runtime_environment.docker_responds",
                side_effect=responds,
            ):
                result = configure_docker_cli(
                    env,
                    root / "runtime",
                )

            wrapper = root / "runtime" / "bin" / "docker"
            self.assertTrue(result["configured"])
            self.assertEqual(
                result["source"],
                "docker-desktop-windows-cli",
            )
            self.assertEqual(wrapper.resolve(), desktop.resolve())
            self.assertTrue(env["PATH"].startswith(str(wrapper.parent)))


if __name__ == "__main__":
    unittest.main()
