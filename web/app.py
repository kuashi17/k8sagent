#!/usr/bin/env python3
"""Small Web UI for the Kubebuilder Agent MVP.

The web layer is intentionally thin. It does not reimplement Agent logic; it
calls the existing CLI orchestrator so CLI, CI, and Web UI all share the same
core behavior.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llm.client import LLMUnavailable, warm_up_model  # noqa: E402


LOG_ROOT = REPO_ROOT / "logs" / "web"
PROFILE_DIR = REPO_ROOT / "profiles"

app = FastAPI(title="Kubebuilder Agent MVP")
app.mount("/static", StaticFiles(directory=REPO_ROOT / "web" / "static"), name="static")
templates = Jinja2Templates(directory=REPO_ROOT / "web" / "templates")


@app.on_event("startup")
def warm_local_llm() -> None:
    if os.environ.get("LOCAL_LLM_WARMUP", "true").lower() in {"0", "false", "no"}:
        return
    try:
        warm_up_model()
        print("Local LLM warm-up completed.")
    except LLMUnavailable as exc:
        print(f"Local LLM warm-up skipped: {exc}")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "profiles": list_profiles(),
            "default_requirement": read_text(REPO_ROOT / "requirements" / "appconfig.txt"),
            "default_log_dir": "logs/e2e/20260607-213346",
            "selected_profile": "",
            "selected_mode": "dry-run",
            "selected_run_level": "fast",
            "result": None,
        },
    )


@app.post("/run-requirement", response_class=HTMLResponse)
async def run_requirement(request: Request) -> HTMLResponse:
    form = await request.form()
    requirement_text = str(form.get("requirement_text") or "").strip()
    profile = str(form.get("profile") or "")
    mode = str(form.get("mode") or "dry-run")
    run_level = str(form.get("run_level") or "fast")
    kind_deploy = str(form.get("kind_deploy") or "") == "on"
    resume_existing = str(form.get("resume_existing") or "") == "on"
    confirm_execute = str(form.get("confirm_execute") or "") == "on"
    planner = "llm"
    if mode == "execute" and not confirm_execute:
        result = {
            "title": "Execution blocked",
            "command": "",
            "stdout": "",
            "stderr": "Execute mode requires the explicit confirmation checkbox.",
            "exit_code": 2,
            "agent_log_dir": "",
            "agent_report": "",
            "summary_json": "",
            "evidence_json": "",
            "safety_json": "",
            "recovery_json": "",
        }
        return render_result(
            request,
            result,
            requirement_text=requirement_text,
            selected_profile=profile,
            selected_planner=planner,
            selected_mode=mode,
            selected_run_level=run_level,
        )

    run_dir = make_run_dir("requirement")
    requirement_path = run_dir / "requirement.txt"
    requirement_path.write_text(requirement_text, encoding="utf-8")

    command = [
        "python3",
        "agent/langchain_agent.py",
        "--requirement",
        str(requirement_path.relative_to(REPO_ROOT)),
        "--mode",
        mode,
        "--run-level",
        run_level,
    ]
    if profile:
        command.extend(["--profile", profile])
    if mode == "execute":
        command.append("--execute")
    if kind_deploy:
        command.append("--kind-deploy")
    if resume_existing:
        command.append("--resume-existing")
    result = run_agent_command(command)
    return render_result(
        request,
        result,
        requirement_text=requirement_text,
        selected_profile=profile,
        selected_planner=planner,
        selected_mode=mode,
        selected_run_level=run_level,
    )


@app.post("/analyze-log", response_class=HTMLResponse)
async def analyze_log(request: Request) -> HTMLResponse:
    form = await request.form()
    log_dir = str(form.get("log_dir") or "").strip()
    planner = "llm"

    command = [
        "python3",
        "agent/langchain_agent.py",
        "--analyze-log",
        log_dir,
    ]
    result = run_agent_command(command)
    return render_result(request, result, selected_planner=planner)


@app.get("/runs/{run_type}/{run_id}", response_class=HTMLResponse)
async def view_web_run(request: Request, run_type: str, run_id: str) -> HTMLResponse:
    run_dir = LOG_ROOT / run_type / run_id
    if not run_dir.is_dir():
        return RedirectResponse("/")
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "profiles": list_profiles(),
            "default_requirement": read_text(run_dir / "requirement.txt"),
            "default_log_dir": "logs/e2e/20260607-213346",
            "result": {
                "title": f"Web Run {run_id}",
                "command": "",
                "stdout": "",
                "stderr": "",
                "exit_code": "",
                "agent_log_dir": "",
                "agent_report": "",
                "web_run_dir": str(run_dir.relative_to(REPO_ROOT)),
            },
        },
    )


def render_result(
    request: Request,
    result: dict[str, Any],
    requirement_text: str | None = None,
    selected_profile: str = "",
    selected_planner: str = "llm",
    selected_mode: str = "dry-run",
    selected_run_level: str = "fast",
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "profiles": list_profiles(),
            "default_requirement": requirement_text or read_text(REPO_ROOT / "requirements" / "appconfig.txt"),
            "default_log_dir": "logs/e2e/20260607-213346",
            "selected_profile": selected_profile,
            "selected_planner": selected_planner,
            "selected_mode": selected_mode,
            "selected_run_level": selected_run_level,
            "result": result,
        },
    )


def run_agent_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    stdout = completed.stdout
    stderr = completed.stderr
    agent_log_dir = extract_agent_log_dir(stdout)
    report = read_agent_report(agent_log_dir)
    summary = read_agent_json(agent_log_dir, "summary.json")
    evidence = read_agent_json(agent_log_dir, "evidence-trace.json")
    safety = read_agent_json(agent_log_dir, "safety-evaluation.json")
    recovery = (summary.get("recovery") or {}) if isinstance(summary, dict) else {}
    return {
        "title": "Agent Result",
        "command": " ".join(command),
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": completed.returncode,
        "agent_log_dir": agent_log_dir,
        "agent_report": report,
        "summary_json": pretty_json(summary),
        "evidence_json": pretty_json(evidence),
        "safety_json": pretty_json(safety),
        "recovery_json": pretty_json(recovery),
    }


def extract_agent_log_dir(stdout: str) -> str:
    match = re.search(r"Agent logs:\s*(\S+)", stdout)
    return match.group(1) if match else ""


def read_agent_report(agent_log_dir: str) -> str:
    if not agent_log_dir:
        return ""
    report_path = REPO_ROOT / agent_log_dir / "agent-report.md"
    return read_text(report_path)


def read_agent_json(agent_log_dir: str, name: str) -> dict[str, Any]:
    if not agent_log_dir:
        return {}
    path = REPO_ROOT / agent_log_dir / name
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def pretty_json(value: dict[str, Any]) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False) if value else ""


def list_profiles() -> list[dict[str, str]]:
    profiles: list[dict[str, str]] = []
    for path in sorted(PROFILE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "name": str(data.get("profileName") or path.stem),
                "description": compact(str(data.get("description") or "")),
            }
        )
    return profiles


def make_run_dir(kind: str) -> Path:
    run_dir = LOG_ROOT / kind / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def compact(value: str, limit: int = 120) -> str:
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 3]}..."


def escape(value: Any) -> str:
    return html.escape(str(value))
