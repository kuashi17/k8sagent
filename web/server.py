#!/usr/bin/env python3
"""Legacy dependency-free Web UI for the Kubebuilder Agent MVP.

The beginner-facing UI is implemented in web.app. Use this fallback only when
FastAPI dependencies cannot be installed. It serves limited flows using only
Python's standard library:
- requirement dry-run
- log analysis
"""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from agent.llm.client import LLMUnavailable, warm_up_model  # noqa: E402
from web.job_manager import JobManager  # noqa: E402


LOG_ROOT = REPO_ROOT / "logs" / "web"
JOBS = JobManager(REPO_ROOT, LOG_ROOT / "jobs")


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "KubebuilderAgentWeb/0.1"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/static/styles.css":
            self.respond_text(read_text(REPO_ROOT / "web" / "static" / "styles.css"), "text/css")
            return
        if path.startswith("/api/jobs/"):
            if path.endswith("/cancel"):
                self.send_error(405)
                return
            job_id = path.rsplit("/", 1)[-1]
            try:
                job = JOBS.result(job_id)
            except ValueError:
                job = None
            self.respond_json(job or {"error": "job not found"}, status=200 if job else 404)
            return
        if path == "/api/jobs":
            self.respond_json({"jobs": JOBS.list(20)})
            return
        if path.startswith("/runs/job/"):
            job_id = path.rsplit("/", 1)[-1]
            try:
                job = JOBS.result(job_id)
            except ValueError:
                job = None
            if not job:
                self.send_error(404)
                return
            self.respond_html(render_job_page(job))
            return
        self.respond_html(render_page())

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/jobs/") and path.endswith("/cancel"):
            job_id = path.split("/")[-2]
            try:
                job = JOBS.cancel(job_id)
            except ValueError:
                job = None
            self.respond_json(job or {"error": "job not found"}, status=200 if job else 404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = {key: values[0] for key, values in parse_qs(body).items()}

        if path == "/run-requirement":
            requirement_text = form.get("requirement_text", "").strip()
            profile = form.get("profile", "")
            mode = form.get("mode", "dry-run")
            run_level = form.get("run_level", "fast")
            kind_deploy = form.get("kind_deploy") == "on"
            resume_existing = form.get("resume_existing") == "on"
            confirm_execute = form.get("confirm_execute") == "on"
            planner = "llm"
            if mode == "execute" and not confirm_execute:
                result = {
                    "command": "",
                    "stdout": "",
                    "stderr": "Execute mode requires the explicit confirmation checkbox.",
                    "exit_code": "2",
                    "agent_log_dir": "",
                    "agent_report": "",
                }
                self.respond_html(render_page(requirement_text=requirement_text, selected_profile=profile, selected_planner=planner, result=result))
                return
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
            job = JOBS.submit(
                "requirement",
                command,
                metadata={"profile": profile, "mode": mode, "runLevel": run_level},
            )
            self.redirect(f"/runs/job/{job['jobId']}")
            return

        if path == "/analyze-log":
            log_dir = form.get("log_dir", "logs/e2e/20260607-213346").strip()
            planner = "llm"
            command = [
                "python3",
                "agent/langchain_agent.py",
                "--analyze-log",
                log_dir,
            ]
            job = JOBS.submit("log-analysis", command, metadata={"sourceLogDir": log_dir, "planner": planner})
            self.redirect(f"/runs/job/{job['jobId']}")
            return

        self.send_error(404)

    def respond_html(self, text: str) -> None:
        self.respond_text(text, "text/html; charset=utf-8")

    def respond_text(self, text: str, content_type: str) -> None:
        payload = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def respond_json(self, value: object, status: int = 200) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()


def render_page(
    requirement_text: str | None = None,
    selected_profile: str = "profiles/appconfig.yaml",
    selected_planner: str = "llm",
    result: dict[str, str] | None = None,
) -> str:
    requirement = requirement_text if requirement_text is not None else read_text(REPO_ROOT / "requirements" / "appconfig.txt")
    profiles = profile_options(selected_profile)
    result_html = render_result(result) if result else ""
    return f"""<!doctype html>
<html lang="ko">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Kubebuilder Agent MVP</title>
    <link rel="stylesheet" href="/static/styles.css">
  </head>
  <body>
    <header class="topbar">
      <div>
        <h1>Kubebuilder Agent MVP</h1>
        <p>자연어 요구사항과 실행 로그를 Agent가 해석하고, RAG 문서와 Tool 실행 결과를 함께 요약합니다.</p>
      </div>
      <div class="badge">Dry-run first</div>
    </header>
    <main class="layout">
      <section class="panel">
        <div class="panel-header">
          <h2>Requirement Dry-run</h2>
          <span>자연어 요구사항 → RAG 검색 → Tool dry-run</span>
        </div>
        <form method="post" action="/run-requirement">
          <label for="requirement_text">Operator requirement</label>
          <textarea id="requirement_text" name="requirement_text" spellcheck="false">{escape(requirement)}</textarea>
          <div class="form-grid">
            <label>Profile hint<select name="profile">{profiles}</select></label>
            <label>Run level<select name="run_level"><option value="fast">fast</option><option value="standard">standard</option></select></label>
            <label>Mode<select name="mode"><option value="dry-run">dry-run</option><option value="execute">execute</option></select></label>
            <div class="field-note">Planner: <strong>local LLM</strong></div>
          </div>
          <div class="option-list">
            <label class="check"><input type="checkbox" name="kind_deploy"> profile 기반 kind 배포 포함</label>
            <label class="check"><input type="checkbox" name="resume_existing"> 기존 scaffold에서 계속</label>
            <label class="check critical"><input type="checkbox" name="confirm_execute"> 실제 변경 승인</label>
          </div>
          <button type="submit">Run Agent Workflow</button>
        </form>
      </section>
      <section class="panel">
        <div class="panel-header">
          <h2>Log Analysis</h2>
          <span>summary.json + analysis.md + troubleshooting RAG</span>
        </div>
        <form method="post" action="/analyze-log">
          <label for="log_dir">Log directory</label>
          <input id="log_dir" name="log_dir" value="logs/e2e/20260607-213346">
          <div class="field-note">Planner: <strong>llm</strong></div>
          <button type="submit">Analyze Log</button>
        </form>
        <div class="note">
          <strong>Safety:</strong> execute 모드는 명시적 승인 체크가 필요하고, kind 배포는 profile capability가 있어야 합니다.
        </div>
      </section>
      {result_html}
    </main>
  </body>
</html>"""


def render_result(result: dict[str, str]) -> str:
    return f"""
      <section class="panel result-panel">
        <div class="panel-header">
          <h2>Result</h2>
          <span>exitCode={escape(result.get("exit_code", ""))}</span>
        </div>
        <div class="meta-grid">
          <div><strong>Command</strong><code>{escape(result.get("command", ""))}</code></div>
          <div><strong>Agent logs</strong><code>{escape(result.get("agent_log_dir", ""))}</code></div>
        </div>
        <h3>Agent Report</h3>
        <pre class="report">{escape(result.get("agent_report", ""))}</pre>
        <details><summary>stdout</summary><pre>{escape(result.get("stdout", ""))}</pre></details>
        <details><summary>stderr</summary><pre>{escape(result.get("stderr", ""))}</pre></details>
      </section>
    """


def render_job_page(job: dict[str, object]) -> str:
    terminal = job.get("state") in {"succeeded", "failed", "canceled", "interrupted"}
    result_html = ""
    if terminal:
        result_html = render_result(
            {
                "command": str(job.get("commandText") or ""),
                "stdout": str(job.get("stdoutTail") or ""),
                "stderr": str(job.get("stderrTail") or ""),
                "exit_code": str(job.get("exitCode") or ""),
                "agent_log_dir": str(job.get("agentLogDir") or ""),
                "agent_report": str(job.get("agentReport") or ""),
            }
        )
    refresh_script = (
        ""
        if terminal
        else f"""<script>
        async function poll() {{
          const response = await fetch('/api/jobs/{escape(job.get("jobId", ""))}', {{cache: 'no-store'}});
          const value = await response.json();
          document.getElementById('state').textContent = value.state;
          document.getElementById('phase').textContent = value.phase;
          document.getElementById('stdout').textContent = value.stdoutTail || '';
          document.getElementById('stderr').textContent = value.stderrTail || '';
          if (['succeeded', 'failed', 'canceled', 'interrupted'].includes(value.state)) window.location.reload();
          else setTimeout(poll, 1200);
        }}
        setTimeout(poll, 500);
        </script>"""
    )
    cancel_button = (
        f"""<button type="button" class="cancel-button" id="cancel-job">Cancel Job</button>
<script>
document.getElementById('cancel-job').addEventListener('click', async () => {{
  await fetch('/api/jobs/{escape(job.get("jobId", ""))}/cancel', {{method: 'POST'}});
  window.location.reload();
}});
</script>"""
        if not terminal
        else ""
    )
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Job</title><link rel="stylesheet" href="/static/styles.css"></head>
<body><header class="topbar"><div><h1>Agent Background Job</h1><p>작업 ID 기반 비동기 실행</p></div>
<div class="badge" id="state">{escape(job.get("state", ""))}</div></header>
<main class="layout"><section class="panel result-panel"><div class="panel-header"><h2>{escape(job.get("jobId", ""))}</h2>
<span id="phase">{escape(job.get("phase", ""))}</span></div>
{cancel_button}
<h3>Live stdout</h3><pre id="stdout">{escape(job.get("stdoutTail", ""))}</pre>
<details><summary>Live stderr</summary><pre id="stderr">{escape(job.get("stderrTail", ""))}</pre></details></section>
{result_html}</main>{refresh_script}</body></html>"""


def profile_options(selected: str) -> str:
    selected_attr = " selected" if not selected else ""
    options = [f'<option value=""{selected_attr}>없음 - requirement 기반 자동 판단</option>']
    for path in sorted((REPO_ROOT / "profiles").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rel = str(path.relative_to(REPO_ROOT))
        label = f"{data.get('profileName') or path.stem} - {rel}"
        selected_attr = " selected" if rel == selected else ""
        options.append(f'<option value="{escape(rel)}"{selected_attr}>{escape(label)}</option>')
    return "\n".join(options)


def make_run_dir(kind: str) -> Path:
    run_dir = LOG_ROOT / kind / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def main() -> int:
    host = "0.0.0.0"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    if os.environ.get("LOCAL_LLM_WARMUP", "true").lower() not in {"0", "false", "no"}:
        try:
            warm_up_model()
            print("Local LLM warm-up completed.")
        except LLMUnavailable as exc:
            print(f"Local LLM warm-up skipped: {exc}")
    server = ThreadingHTTPServer((host, port), AgentHandler)
    print(
        "Legacy fallback UI. For the beginner-facing UI run: "
        "uvicorn web.app:app --host 0.0.0.0 --port 8000"
    )
    print(f"Kubebuilder Agent fallback UI: http://localhost:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
