#!/usr/bin/env python3
"""Small Web UI for the Kubebuilder Agent MVP.

The web layer is intentionally thin. It does not reimplement Agent logic; it
calls the existing CLI orchestrator so CLI, CI, and Web UI all share the same
core behavior.
"""

from __future__ import annotations

import asyncio
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llm.client import LLMUnavailable, warm_up_model  # noqa: E402
from web.job_manager import JobManager  # noqa: E402


LOG_ROOT = REPO_ROOT / "logs" / "web"
PROFILE_DIR = REPO_ROOT / "profiles"
JOB_ROOT = LOG_ROOT / "jobs"

app = FastAPI(title="Kubebuilder Agent MVP")
app.mount("/static", StaticFiles(directory=REPO_ROOT / "web" / "static"), name="static")
templates = Jinja2Templates(directory=REPO_ROOT / "web" / "templates")
jobs = JobManager(REPO_ROOT, JOB_ROOT)


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
            "job": None,
            "recent_jobs": jobs.list(10),
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
        return render_result(request, result, requirement_text=requirement_text, selected_profile=profile, selected_planner=planner, selected_mode=mode, selected_run_level=run_level)

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
    job = jobs.submit(
        "requirement",
        command,
        metadata={
            "requirementPath": str(requirement_path.relative_to(REPO_ROOT)),
            "profile": profile,
            "mode": mode,
            "runLevel": run_level,
            "kindDeploy": kind_deploy,
            "resumeExisting": resume_existing,
        },
    )
    return RedirectResponse(f"/runs/job/{job['jobId']}", status_code=303)


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
    job = jobs.submit("log-analysis", command, metadata={"sourceLogDir": log_dir, "planner": planner})
    return RedirectResponse(f"/runs/job/{job['jobId']}", status_code=303)


@app.get("/runs/{run_type}/{run_id}", response_class=HTMLResponse)
async def view_web_run(request: Request, run_type: str, run_id: str) -> HTMLResponse:
    if run_type == "job":
        job = jobs.result(run_id)
        if not job:
            return RedirectResponse("/")
        metadata = job.get("metadata") or {}
        requirement_path = metadata.get("requirementPath") or ""
        requirement_text = read_text(REPO_ROOT / requirement_path) if requirement_path else None
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=page_context(
                request,
                result=result_from_job(job) if job.get("state") in {"succeeded", "failed"} else None,
                job=job,
                requirement_text=requirement_text,
                selected_profile=str(metadata.get("profile") or ""),
                selected_mode=str(metadata.get("mode") or "dry-run"),
                selected_run_level=str(metadata.get("runLevel") or "fast"),
            ),
        )
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
            "job": None,
            "recent_jobs": jobs.list(10),
        },
    )


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> JSONResponse:
    try:
        job = jobs.result(job_id)
    except ValueError:
        job = None
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return JSONResponse(
        {
            "jobId": job.get("jobId"),
            "state": job.get("state"),
            "phase": job.get("phase"),
            "exitCode": job.get("exitCode"),
            "createdAt": job.get("createdAt"),
            "startedAt": job.get("startedAt"),
            "finishedAt": job.get("finishedAt"),
            "agentLogDir": job.get("agentLogDir"),
            "stdoutTail": job.get("stdoutTail"),
            "stderrTail": job.get("stderrTail"),
            "terminal": job.get("state")
            in {"succeeded", "failed", "canceled", "interrupted"},
            "attempt": job.get("attempt"),
            "maxAttempts": job.get("maxAttempts"),
            "rollbackPolicy": job.get("rollbackPolicy") or {},
        }
    )


@app.get("/api/jobs")
async def job_list(limit: int = 20) -> JSONResponse:
    return JSONResponse({"jobs": jobs.list(limit)})


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> JSONResponse:
    try:
        job = jobs.cancel(job_id)
    except ValueError:
        job = None
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return JSONResponse(
        {
            "jobId": job.get("jobId"),
            "state": job.get("state"),
            "phase": job.get("phase"),
        }
    )


@app.post("/api/jobs/{job_id}/retry")
async def retry_job(job_id: str) -> JSONResponse:
    try:
        job = jobs.retry(job_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=409)
    if not job:
        return JSONResponse({"error": "job not found"}, status_code=404)
    return JSONResponse(
        {
            "jobId": job.get("jobId"),
            "state": job.get("state"),
            "attempt": job.get("attempt"),
        },
        status_code=201,
    )


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    async def stream():
        previous = ""
        while True:
            try:
                job = jobs.get(job_id)
            except ValueError:
                job = None
            if not job:
                yield 'event: error\ndata: {"error":"job not found"}\n\n'
                return
            payload = json.dumps(
                {
                    "jobId": job.get("jobId"),
                    "state": job.get("state"),
                    "phase": job.get("phase"),
                    "exitCode": job.get("exitCode"),
                    "agentLogDir": job.get("agentLogDir"),
                    "stdoutTail": job.get("stdoutTail"),
                    "stderrTail": job.get("stderrTail"),
                    "terminal": job.get("state") in {
                        "succeeded",
                        "failed",
                        "canceled",
                        "interrupted",
                    },
                },
                ensure_ascii=False,
            )
            if payload != previous:
                yield f"data: {payload}\n\n"
                previous = payload
            if job.get("state") in {
                "succeeded",
                "failed",
                "canceled",
                "interrupted",
            }:
                return
            await asyncio.sleep(0.75)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
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
        context=page_context(
            request=request,
            result=result,
            requirement_text=requirement_text,
            selected_profile=selected_profile,
            selected_planner=selected_planner,
            selected_mode=selected_mode,
            selected_run_level=selected_run_level,
        ),
    )


def page_context(
    request: Request | None = None,
    *,
    result: dict[str, Any] | None = None,
    job: dict[str, Any] | None = None,
    requirement_text: str | None = None,
    selected_profile: str = "",
    selected_planner: str = "llm",
    selected_mode: str = "dry-run",
    selected_run_level: str = "fast",
) -> dict[str, Any]:
    return {
        "request": request,
        "profiles": list_profiles(),
        "default_requirement": requirement_text or read_text(REPO_ROOT / "requirements" / "appconfig.txt"),
        "default_log_dir": "logs/e2e/20260607-213346",
        "selected_profile": selected_profile,
        "selected_planner": selected_planner,
        "selected_mode": selected_mode,
        "selected_run_level": selected_run_level,
        "result": result,
        "job": job,
        "recent_jobs": jobs.list(10),
    }


def result_from_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": "Agent Result",
        "command": job.get("commandText") or "",
        "stdout": job.get("stdoutTail") or "",
        "stderr": job.get("stderrTail") or "",
        "exit_code": job.get("exitCode"),
        "agent_log_dir": job.get("agentLogDir") or "",
        "agent_report": job.get("agentReport") or "",
        "summary_json": pretty_json(job.get("summary") or {}),
        "evidence_json": pretty_json(job.get("evidence") or {}),
        "safety_json": pretty_json(job.get("safety") or {}),
        "recovery_json": pretty_json(job.get("recovery") or {}),
    }


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
    run_dir = LOG_ROOT / kind / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def compact(value: str, limit: int = 120) -> str:
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= limit else f"{cleaned[: limit - 3]}..."


def escape(value: Any) -> str:
    return html.escape(str(value))
