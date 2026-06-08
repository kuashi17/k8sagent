#!/usr/bin/env python3
"""Dependency-free Web UI for the Kubebuilder Agent MVP.

Use this when FastAPI dependencies are not installed. It serves the same basic
flows using only Python's standard library:
- requirement dry-run
- log analysis
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = REPO_ROOT / "logs" / "web"


class AgentHandler(BaseHTTPRequestHandler):
    server_version = "KubebuilderAgentWeb/0.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/static/styles.css":
            self.respond_text(read_text(REPO_ROOT / "web" / "static" / "styles.css"), "text/css")
            return
        self.respond_html(render_page())

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = {key: values[0] for key, values in parse_qs(body).items()}

        if self.path == "/run-requirement":
            requirement_text = form.get("requirement_text", "").strip()
            profile = form.get("profile", "profiles/appconfig.yaml")
            planner = form.get("planner", "mock")
            run_dir = make_run_dir("requirement")
            requirement_path = run_dir / "requirement.txt"
            requirement_path.write_text(requirement_text, encoding="utf-8")
            command = [
                "python3",
                "agent/langchain_agent.py",
                "--requirement",
                str(requirement_path.relative_to(REPO_ROOT)),
                "--profile",
                profile,
                "--planner",
                planner,
                "--mode",
                "dry-run",
            ]
            result = run_agent(command)
            self.respond_html(render_page(requirement_text=requirement_text, selected_profile=profile, selected_planner=planner, result=result))
            return

        if self.path == "/analyze-log":
            log_dir = form.get("log_dir", "logs/e2e/20260607-213346").strip()
            planner = form.get("planner", "mock")
            command = [
                "python3",
                "agent/langchain_agent.py",
                "--analyze-log",
                log_dir,
                "--planner",
                planner,
            ]
            result = run_agent(command)
            self.respond_html(render_page(selected_planner=planner, result=result))
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


def render_page(
    requirement_text: str | None = None,
    selected_profile: str = "profiles/appconfig.yaml",
    selected_planner: str = "mock",
    result: dict[str, str] | None = None,
) -> str:
    requirement = requirement_text if requirement_text is not None else read_text(REPO_ROOT / "requirements" / "appconfig.txt")
    profiles = profile_options(selected_profile)
    planners = planner_options(selected_planner)
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
            <label>Profile<select name="profile">{profiles}</select></label>
            <label>Planner<select name="planner">{planners}</select></label>
          </div>
          <button type="submit">Run Dry-run Agent</button>
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
          <label>Planner<select name="planner">{planners}</select></label>
          <button type="submit">Analyze Log</button>
        </form>
        <div class="note">
          <strong>Safety:</strong> 이 Web UI는 실제 scaffold/e2e execute 버튼을 제공하지 않습니다.
          실제 변경 작업은 CLI에서 명시적으로 <code>--execute</code>를 사용할 때만 수행합니다.
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


def profile_options(selected: str) -> str:
    options = []
    for path in sorted((REPO_ROOT / "profiles").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rel = str(path.relative_to(REPO_ROOT))
        label = f"{data.get('profileName') or path.stem} - {rel}"
        selected_attr = " selected" if rel == selected else ""
        options.append(f'<option value="{escape(rel)}"{selected_attr}>{escape(label)}</option>')
    return "\n".join(options)


def planner_options(selected: str) -> str:
    return "\n".join(
        f'<option value="{item}"{" selected" if item == selected else ""}>{item}</option>'
        for item in ["mock", "local", "llm"]
    )


def run_agent(command: list[str]) -> dict[str, str]:
    completed = subprocess.run(command, cwd=REPO_ROOT, text=True, capture_output=True)
    stdout = completed.stdout
    agent_log_dir = extract_agent_log_dir(stdout)
    return {
        "command": " ".join(command),
        "stdout": stdout,
        "stderr": completed.stderr,
        "exit_code": str(completed.returncode),
        "agent_log_dir": agent_log_dir,
        "agent_report": read_agent_report(agent_log_dir),
    }


def extract_agent_log_dir(stdout: str) -> str:
    match = re.search(r"Agent logs:\s*(\S+)", stdout)
    return match.group(1) if match else ""


def read_agent_report(agent_log_dir: str) -> str:
    if not agent_log_dir:
        return ""
    return read_text(REPO_ROOT / agent_log_dir / "agent-report.md")


def make_run_dir(kind: str) -> Path:
    run_dir = LOG_ROOT / kind / datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def main() -> int:
    host = "0.0.0.0"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer((host, port), AgentHandler)
    print(f"Kubebuilder Agent Web UI: http://localhost:{port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
