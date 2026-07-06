"""Prepare local runtime tools used by Web worker subprocesses."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import MutableMapping


DOCKER_DESKTOP_CLI = Path(
    "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe"
)


def configure_docker_cli(
    environment: MutableMapping[str, str] | None = None,
    runtime_root: Path | None = None,
) -> dict[str, str | bool]:
    """Select a Docker CLI that can reach a daemon and expose it via PATH.

    Docker Desktop's WSL symlink can exist while its Unix socket is absent.
    In that state the Windows CLI still reaches the same Desktop daemon. A
    private wrapper directory lets kind and child tools consistently resolve
    the working CLI without modifying system files.
    """
    env = environment if environment is not None else os.environ
    current = shutil.which("docker", path=env.get("PATH"))
    if current and docker_responds(Path(current), env):
        return {
            "configured": False,
            "source": "existing-path",
            "docker": current,
        }

    configured = str(env.get("K8SAGENT_DOCKER_CLI") or "").strip()
    candidate = Path(configured) if configured else DOCKER_DESKTOP_CLI
    if not candidate.is_file() or not docker_responds(candidate, env):
        return {
            "configured": False,
            "source": "unavailable",
            "docker": current or "",
        }

    root = runtime_root or Path.home() / ".cache" / "k8sagent" / "web-runtime"
    binary_dir = root / "bin"
    binary_dir.mkdir(parents=True, exist_ok=True)
    wrapper = binary_dir / "docker"
    if wrapper.exists() or wrapper.is_symlink():
        wrapper.unlink()
    wrapper.symlink_to(candidate)
    current_path = str(env.get("PATH") or "")
    env["PATH"] = (
        f"{binary_dir}{os.pathsep}{current_path}"
        if current_path
        else str(binary_dir)
    )
    return {
        "configured": True,
        "source": "docker-desktop-windows-cli",
        "docker": str(wrapper),
    }


def docker_responds(
    executable: Path,
    environment: MutableMapping[str, str],
) -> bool:
    try:
        completed = subprocess.run(
            [str(executable), "info", "--format", "{{.ServerVersion}}"],
            env=dict(environment),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0 and bool(completed.stdout.strip())
