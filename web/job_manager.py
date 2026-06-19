"""Persistent background job execution for the Web UI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


AGENT_LOG_PATTERN = re.compile(r"Agent logs:\s*(\S+)")
TERMINAL_STATES = {"succeeded", "failed", "canceled", "interrupted"}


class JobManager:
    def __init__(self, repo_root: Path, root: Path) -> None:
        self.repo_root = repo_root
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._recover_interrupted_jobs()

    def submit(
        self,
        job_type: str,
        command: list[str],
        *,
        metadata: dict[str, Any] | None = None,
        input_files: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        job_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        job_dir = self.root / job_id
        job_dir.mkdir(parents=True)
        for name, content in (input_files or {}).items():
            safe_path = job_dir / Path(name).name
            safe_path.write_text(content, encoding="utf-8")
        status = {
            "jobId": job_id,
            "jobType": job_type,
            "state": "queued",
            "phase": "queued",
            "command": command,
            "commandText": " ".join(command),
            "metadata": metadata or {},
            "createdAt": now_iso(),
            "startedAt": "",
            "finishedAt": "",
            "exitCode": None,
            "agentLogDir": "",
            "jobDir": relative(job_dir, self.repo_root),
        }
        self._write_status(job_dir, status)
        thread = threading.Thread(target=self._run, args=(job_dir, status), daemon=True, name=f"web-job-{job_id}")
        thread.start()
        return status

    def get(self, job_id: str, *, tail_chars: int = 16000) -> dict[str, Any] | None:
        job_dir = self.root / safe_job_id(job_id)
        status_path = job_dir / "status.json"
        if not status_path.is_file():
            return None
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        stdout = read_tail(job_dir / "stdout.log", tail_chars)
        stderr = read_tail(job_dir / "stderr.log", tail_chars)
        if status.get("state") not in TERMINAL_STATES:
            status["phase"] = infer_phase(stdout, status.get("phase") or "running")
        status["stdoutTail"] = stdout
        status["stderrTail"] = stderr
        return status

    def result(self, job_id: str) -> dict[str, Any] | None:
        status = self.get(job_id, tail_chars=200000)
        if not status:
            return None
        agent_log_dir = str(status.get("agentLogDir") or "")
        summary = read_json(self.repo_root / agent_log_dir / "summary.json") if agent_log_dir else {}
        return {
            **status,
            "agentReport": read_text(self.repo_root / agent_log_dir / "agent-report.md") if agent_log_dir else "",
            "summary": summary,
            "evidence": read_json(self.repo_root / agent_log_dir / "evidence-trace.json") if agent_log_dir else {},
            "safety": read_json(self.repo_root / agent_log_dir / "safety-evaluation.json") if agent_log_dir else {},
            "recovery": (summary.get("recovery") or {}) if isinstance(summary, dict) else {},
        }

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        jobs = []
        for status_path in self.root.glob("*/status.json"):
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            jobs.append(status)
        jobs.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
        return jobs[: max(1, min(limit, 100))]

    def cancel(self, job_id: str) -> dict[str, Any] | None:
        safe_id = safe_job_id(job_id)
        job_dir = self.root / safe_id
        with self._lock:
            status = self._read_status(job_dir)
            if not status:
                return None
            if status.get("state") in TERMINAL_STATES:
                return self.get(safe_id)
            status.update(
                {
                    "state": "canceled",
                    "phase": "canceled",
                    "finishedAt": now_iso(),
                    "exitCode": -15,
                }
            )
            self._write_status(job_dir, status)
            process = self._processes.get(safe_id)
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        return self.get(safe_id)

    def _run(self, job_dir: Path, status: dict[str, Any]) -> None:
        with self._lock:
            current = self._read_status(job_dir)
            if not current or current.get("state") == "canceled":
                return
            status = dict(status)
            status.update({"state": "running", "phase": "starting", "startedAt": now_iso()})
            self._write_status(job_dir, status)
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        with (job_dir / "stdout.log").open("w", encoding="utf-8") as stdout_file, (
            job_dir / "stderr.log"
        ).open("w", encoding="utf-8") as stderr_file:
            try:
                process = subprocess.Popen(
                    status["command"],
                    cwd=self.repo_root,
                    text=True,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    env=env,
                )
                with self._lock:
                    self._processes[status["jobId"]] = process
                    current = self._read_status(job_dir)
                    canceled = bool(current and current.get("state") == "canceled")
                if canceled and process.poll() is None:
                    process.terminate()
                exit_code = process.wait()
                state = "succeeded" if exit_code == 0 else "failed"
            except Exception as exc:  # noqa: BLE001
                stderr_file.write(f"\nWeb job execution failed: {exc}\n")
                exit_code = 1
                state = "failed"
            finally:
                with self._lock:
                    self._processes.pop(status["jobId"], None)
        stdout = read_text(job_dir / "stdout.log")
        match = AGENT_LOG_PATTERN.search(stdout)
        with self._lock:
            current = self._read_status(job_dir)
            if current and current.get("state") == "canceled":
                return
            status.update(
                {
                    "state": state,
                    "phase": "completed" if state == "succeeded" else "failed",
                    "finishedAt": now_iso(),
                    "exitCode": exit_code,
                    "agentLogDir": match.group(1) if match else "",
                }
            )
            self._write_status(job_dir, status)

    def _write_status(self, job_dir: Path, status: dict[str, Any]) -> None:
        payload = json.dumps(status, indent=2, ensure_ascii=False)
        temp = job_dir / "status.json.tmp"
        with self._lock:
            temp.write_text(payload, encoding="utf-8")
            temp.replace(job_dir / "status.json")

    @staticmethod
    def _read_status(job_dir: Path) -> dict[str, Any] | None:
        try:
            status = json.loads((job_dir / "status.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return status if isinstance(status, dict) else None

    def _recover_interrupted_jobs(self) -> None:
        for status_path in self.root.glob("*/status.json"):
            try:
                status = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if status.get("state") not in {"queued", "running"}:
                continue
            status.update(
                {
                    "state": "interrupted",
                    "phase": "server restarted",
                    "finishedAt": now_iso(),
                    "exitCode": None,
                }
            )
            self._write_status(status_path.parent, status)


def infer_phase(stdout: str, fallback: str) -> str:
    phases = [
        ("Calling tool: kind_deployment", "kind deployment"),
        ("Calling tool: validation", "validation"),
        ("Calling tool: artifact_patcher", "artifact patch"),
        ("Calling tool: scaffold_runner", "scaffold"),
        ("Calling tool: command_planner", "command planning"),
        ("Calling tool: spec_generator", "spec generation"),
        ("Planner cache:", "LLM planning completed"),
        ("LLM Agent Orchestrator", "LLM planning"),
        ("LLM Agent Log Analysis", "log analysis"),
    ]
    for marker, phase in phases:
        if marker in stdout:
            return phase
    return fallback


def safe_job_id(value: str) -> str:
    if not re.fullmatch(r"[0-9A-Za-z-]+", value):
        raise ValueError("Invalid job ID")
    return value


def read_tail(path: Path, limit: int) -> str:
    text = read_text(path)
    return text[-limit:]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
