#!/usr/bin/env python3
"""Beginner-facing FastAPI UI for the Kubebuilder Agent."""

from __future__ import annotations

import asyncio
import json
import os
import sys
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
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llm.client import LLMUnavailable, warm_up_model  # noqa: E402
from web.job_manager import JobManager, TERMINAL_STATES  # noqa: E402
from web.result_presenter import (  # noqa: E402
    developer_details,
    present_log_analysis_result,
    present_run_result,
)
from web.schemas import LogAnalysisRequest, RequirementRunRequest  # noqa: E402
from web.workflow_service import WorkflowService  # noqa: E402


LOG_ROOT = REPO_ROOT / "logs" / "web"
PROFILE_DIR = REPO_ROOT / "profiles"
JOB_ROOT = LOG_ROOT / "jobs"

STATE_LABELS = {
    "queued": "대기 중",
    "running": "진행 중",
    "succeeded": "완료",
    "failed": "실패",
    "canceled": "취소됨",
    "interrupted": "중단됨",
}

PHASE_LABELS = {
    "queued": "작업 준비",
    "starting": "Agent 시작",
    "LLM planning": "요구사항 분석과 계획 생성",
    "LLM planning completed": "계획 생성 완료",
    "spec generation": "Operator 구조 설계",
    "command planning": "안전한 실행 순서 구성",
    "scaffold": "프로젝트 생성",
    "artifact patch": "Controller 코드 생성",
    "validation": "코드와 테스트 검증",
    "kind deployment": "로컬 클러스터 검증",
    "completed": "결과 정리 완료",
    "failed": "오류 확인",
    "canceled": "작업 취소",
    "interrupted": "작업 중단",
}

app = FastAPI(title="Kubebuilder Agent")
app.mount(
    "/static",
    StaticFiles(directory=REPO_ROOT / "web" / "static"),
    name="static",
)
templates = Jinja2Templates(directory=REPO_ROOT / "web" / "templates")
jobs = JobManager(REPO_ROOT, JOB_ROOT)
workflows = WorkflowService(REPO_ROOT, LOG_ROOT, PROFILE_DIR)


@app.on_event("startup")
def warm_local_llm() -> None:
    if os.environ.get("LOCAL_LLM_WARMUP", "true").lower() in {
        "0",
        "false",
        "no",
    }:
        return
    try:
        warm_up_model()
        print("Local LLM warm-up completed.")
    except LLMUnavailable as exc:
        print(f"Local LLM warm-up skipped: {exc}")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return render_home(request)


@app.post("/run-requirement", response_class=HTMLResponse)
async def run_requirement(request: Request) -> HTMLResponse:
    form = await request.form()
    try:
        run_request = RequirementRunRequest.from_form(form)
        job = workflows.submit_requirement(run_request, jobs)
    except (ValidationError, ValueError) as exc:
        return render_home(
            request,
            requirement_text=str(form.get("requirement_text") or ""),
            selected_profile=str(form.get("profile") or ""),
            selected_mode=str(form.get("mode") or "dry-run"),
            selected_run_level=str(form.get("run_level") or "fast"),
            form_error=friendly_error(exc),
            status_code=422,
        )
    return RedirectResponse(
        f"/runs/job/{job['jobId']}",
        status_code=303,
    )


@app.post("/analyze-log", response_class=HTMLResponse)
async def analyze_log(request: Request) -> HTMLResponse:
    form = await request.form()
    try:
        if not str(form.get("log_dir") or "").strip():
            raise ValueError("분석할 로그 작업을 먼저 선택해 주세요.")
        analysis = LogAnalysisRequest.from_form(form)
        job = workflows.submit_log_analysis(analysis, jobs)
    except (ValidationError, ValueError) as exc:
        return render_home(
            request,
            default_log_dir=str(form.get("log_dir") or "").strip(),
            log_form_error=friendly_error(exc),
            show_log_analysis=True,
            status_code=422,
        )
    return RedirectResponse(
        f"/runs/job/{job['jobId']}",
        status_code=303,
    )


@app.get("/runs/job/{job_id}", response_class=HTMLResponse)
async def view_job(request: Request, job_id: str) -> HTMLResponse:
    try:
        job = jobs.result(job_id)
    except ValueError:
        job = None
    if not job:
        return RedirectResponse("/")
    metadata = job.get("metadata") or {}
    requirement_path = str(metadata.get("requirementPath") or "")
    requirement_text = (
        read_text(REPO_ROOT / requirement_path)
        if requirement_path
        else ""
    )
    terminal = job.get("state") in TERMINAL_STATES
    is_log_analysis = job.get("jobType") == "log-analysis"
    result_view = (
        present_run_result(job)
        if terminal and not is_log_analysis
        else None
    )
    log_analysis_view = (
        present_log_analysis_result(job)
        if terminal and is_log_analysis
        else None
    )
    return templates.TemplateResponse(
        request=request,
        name="run.html",
        context={
            "request": request,
            "job": job,
            "terminal": terminal,
            "result_view": result_view,
            "log_analysis_view": log_analysis_view,
            "is_log_analysis": is_log_analysis,
            "developer": developer_details(job) if terminal else {},
            "requirement_text": requirement_text,
            "profiles": list_profiles(),
            "selected_profile": str(metadata.get("profile") or ""),
            "selected_run_level": str(
                metadata.get("runLevel") or "fast"
            ),
            "selected_kind_deploy": bool(
                metadata.get("kindDeploy")
            ),
            "selected_resume_existing": bool(
                metadata.get("resumeExisting")
            ),
            "state_labels": STATE_LABELS,
            "phase_labels": PHASE_LABELS,
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
    return JSONResponse(job_status_payload(job))


@app.get("/api/jobs")
async def job_list(limit: int = 20) -> JSONResponse:
    return JSONResponse({"jobs": jobs.list(limit)})


@app.get("/api/health")
async def health() -> JSONResponse:
    recent = jobs.list(100)
    counts = {
        state: sum(1 for item in recent if item.get("state") == state)
        for state in ["queued", "running", *sorted(TERMINAL_STATES)]
    }
    return JSONResponse(
        {
            "status": "ok",
            "service": "kubebuilder-agent-web",
            "executionMode": getattr(jobs, "execution_mode", "embedded"),
            "jobs": counts,
        }
    )


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
                job_status_payload(job),
                ensure_ascii=False,
            )
            if payload != previous:
                yield f"data: {payload}\n\n"
                previous = payload
            if job.get("state") in TERMINAL_STATES:
                return
            await asyncio.sleep(0.75)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def render_home(
    request: Request,
    *,
    requirement_text: str | None = None,
    selected_profile: str = "",
    selected_mode: str = "dry-run",
    selected_run_level: str = "fast",
    form_error: str = "",
    default_log_dir: str = "",
    log_form_error: str = "",
    show_log_analysis: bool = False,
    status_code: int = 200,
) -> HTMLResponse:
    log_options = analyzable_log_options()
    selected_log = default_log_dir or next(
        (
            item["path"]
            for item in log_options
            if item["state"] == "failed"
        ),
        log_options[0]["path"] if log_options else "",
    )
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "request": request,
            "profiles": list_profiles(),
            "default_requirement": requirement_text
            if requirement_text is not None
            else "",
            "default_log_dir": selected_log,
            "log_options": log_options,
            "log_form_error": log_form_error,
            "selected_profile": selected_profile,
            "selected_mode": selected_mode,
            "selected_run_level": selected_run_level,
            "form_error": form_error,
            "show_log_analysis": show_log_analysis,
            "recent_jobs": jobs.list(3),
            "state_labels": STATE_LABELS,
        },
        status_code=status_code,
    )


def analyzable_log_options(limit: int = 20) -> list[dict[str, str]]:
    options = []
    for item in jobs.list(100):
        log_dir = str(item.get("agentLogDir") or "")
        if (
            item.get("jobType") != "requirement"
            or item.get("state") not in TERMINAL_STATES
            or not log_dir
        ):
            continue
        options.append(
            {
                "path": log_dir,
                "state": str(item.get("state") or ""),
                "label": (
                    f"{STATE_LABELS.get(str(item.get('state')), item.get('state'))} · "
                    f"{item.get('createdAt') or ''} · {log_dir}"
                ),
            }
        )
        if len(options) >= limit:
            break
    return options


def job_status_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
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
        "terminal": job.get("state") in TERMINAL_STATES,
        "attempt": job.get("attempt"),
        "maxAttempts": job.get("maxAttempts"),
        "rollbackPolicy": job.get("rollbackPolicy") or {},
        "journeyTimings": job.get("journeyTimings") or {},
    }


def list_profiles() -> list[dict[str, str]]:
    profiles: list[dict[str, str]] = []
    for path in sorted(PROFILE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        profiles.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "name": str(data.get("profileName") or path.stem),
                "description": compact(
                    str(data.get("description") or "")
                ),
            }
        )
    return profiles


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        if first.get("type") == "string_too_short":
            return "어떤 Operator를 만들고 싶은지 조금 더 자세히 적어 주세요."
        return str(first.get("msg") or "입력값을 확인해 주세요.")
    return str(exc)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def compact(value: str, limit: int = 100) -> str:
    cleaned = " ".join(value.split())
    return (
        cleaned
        if len(cleaned) <= limit
        else f"{cleaned[: limit - 3]}..."
    )
