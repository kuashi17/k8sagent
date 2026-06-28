#!/usr/bin/env python3
"""Collect GitHub Full CI queue, job, step, and regression timings."""

from __future__ import annotations

import argparse
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


API_ROOT = "https://api.github.com"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    parser.add_argument("--max-job-seconds", type=float, default=600.0)
    parser.add_argument("--max-observed-seconds", type=float, default=1200.0)
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("GitHub token is required")

    run = api_json(
        f"/repos/{args.repository}/actions/runs/{args.run_id}",
        args.token,
    )
    jobs = api_json(
        f"/repos/{args.repository}/actions/runs/{args.run_id}/jobs"
        "?filter=all&per_page=100",
        args.token,
    )
    job = next(
        (
            item
            for item in jobs.get("jobs") or []
            if item.get("name") == "full"
        ),
        None,
    )
    if not job:
        raise SystemExit("full job was not found")
    regression = download_regression_summary(
        args.repository,
        str(args.run_id),
        args.token,
    )
    report = build_timing_report(
        run,
        job,
        regression,
        args.max_job_seconds,
        args.max_observed_seconds,
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "full-ci-timing.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (output_dir / "full-ci-timing.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["overallBudgetStatus"] == "passed" else 1


def build_timing_report(
    run: dict[str, Any],
    job: dict[str, Any],
    regression: dict[str, Any],
    budget_seconds: float,
    observed_budget_seconds: float = 1200.0,
) -> dict[str, Any]:
    queue_seconds = elapsed(run.get("created_at"), job.get("started_at"))
    job_seconds = elapsed(job.get("started_at"), job.get("completed_at"))
    steps = [step_timing(item) for item in job.get("steps") or []]
    regression_checks = {
        str(item.get("name")): float(item.get("elapsedSeconds") or 0)
        for item in regression.get("checks") or []
    }
    regression_seconds = round(sum(regression_checks.values()), 3)
    categories = aggregate_categories(steps)
    overhead_seconds = (
        round(max(job_seconds - regression_seconds, 0), 3)
        if job_seconds is not None
        else None
    )
    budget_status = (
        "passed"
        if job_seconds is not None and job_seconds <= budget_seconds
        else "failed"
    )
    observed_seconds = (
        round(queue_seconds + job_seconds, 3)
        if queue_seconds is not None and job_seconds is not None
        else None
    )
    observed_budget_status = (
        "passed"
        if observed_seconds is not None
        and observed_seconds <= observed_budget_seconds
        else "failed"
    )
    return {
        "createdAt": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "runId": run.get("id"),
        "runUrl": run.get("html_url"),
        "headSha": run.get("head_sha"),
        "conclusion": job.get("conclusion"),
        "queueSeconds": queue_seconds,
        "jobSeconds": job_seconds,
        "regressionSeconds": regression_seconds,
        "workflowOverheadSeconds": overhead_seconds,
        "budgetSeconds": budget_seconds,
        "budgetStatus": budget_status,
        "observedSeconds": observed_seconds,
        "observedBudgetSeconds": observed_budget_seconds,
        "observedBudgetStatus": observed_budget_status,
        "overallBudgetStatus": (
            "passed"
            if budget_status == "passed"
            and observed_budget_status == "passed"
            else "failed"
        ),
        "categories": categories,
        "regressionChecks": regression_checks,
        "steps": steps,
    }


def step_timing(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(step.get("name") or ""),
        "conclusion": str(step.get("conclusion") or ""),
        "elapsedSeconds": elapsed(
            step.get("started_at"),
            step.get("completed_at"),
        ),
    }


def aggregate_categories(
    steps: list[dict[str, Any]],
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for step in steps:
        name = str(step["name"])
        seconds = float(step.get("elapsedSeconds") or 0)
        category = categorize_step(name)
        totals[category] = totals.get(category, 0) + seconds
    return {
        key: round(value, 3)
        for key, value in sorted(totals.items())
    }


def categorize_step(name: str) -> str:
    lowered = name.lower()
    if "run-regression-tests.py --suite full" in lowered:
        return "regression"
    if "cache" in lowered:
        return "cache"
    if "upload-artifact" in lowered:
        return "artifact-upload"
    if "checkout" in lowered or "set up job" in lowered:
        return "job-setup"
    if "install pinned" in lowered:
        return "tool-bootstrap"
    if "docker info" in lowered:
        return "docker-preflight"
    if "py_compile" in lowered:
        return "python-preflight"
    if "test -f" in lowered:
        return "artifact-validation"
    if "clean up ephemeral" in lowered:
        return "kind-cleanup"
    if "complete job" in lowered:
        return "job-finalize"
    return "other"


def elapsed(start: Any, end: Any) -> float | None:
    if not start or not end:
        return None
    started = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
    completed = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
    return round(max((completed - started).total_seconds(), 0), 3)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Full CI Timing",
        "",
        f"- Budget: {report['budgetSeconds']} seconds",
        f"- Budget status: **{report['budgetStatus']}**",
        f"- Integrated observation budget: {report['observedBudgetSeconds']} seconds",
        f"- Integrated observation status: **{report['observedBudgetStatus']}**",
        f"- Queue + full job: {report['observedSeconds']} seconds",
        f"- Queue: {report['queueSeconds']} seconds",
        f"- Full job: {report['jobSeconds']} seconds",
        f"- Regression: {report['regressionSeconds']} seconds",
        f"- Workflow overhead: {report['workflowOverheadSeconds']} seconds",
        "",
        "## Workflow categories",
        "",
        "| Category | Seconds |",
        "| --- | ---: |",
    ]
    lines.extend(
        f"| {name} | {seconds} |"
        for name, seconds in report["categories"].items()
    )
    lines.extend(
        [
            "",
            "## Regression checks",
            "",
            "| Check | Seconds |",
            "| --- | ---: |",
        ]
    )
    lines.extend(
        f"| {name} | {seconds} |"
        for name, seconds in report["regressionChecks"].items()
    )
    return "\n".join(lines) + "\n"


def download_regression_summary(
    repository: str,
    run_id: str,
    token: str,
) -> dict[str, Any]:
    expected = f"full-regression-{run_id}"
    artifact = None
    for attempt in range(1, 7):
        artifacts = api_json(
            f"/repos/{repository}/actions/runs/{run_id}/artifacts"
            "?per_page=100",
            token,
        )
        artifact = next(
            (
                item
                for item in artifacts.get("artifacts") or []
                if item.get("name") == expected
            ),
            None,
        )
        if artifact or attempt == 6:
            break
        time.sleep(2)
    if not artifact:
        return {}
    archive = api_redirect_bytes(
        f"/repos/{repository}/actions/artifacts/{artifact['id']}/zip",
        token,
    )
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        member = next(
            (
                name
                for name in bundle.namelist()
                if name.endswith("regression-summary.json")
            ),
            "",
        )
        if not member:
            return {}
        return json.loads(bundle.read(member).decode("utf-8"))


def api_json(path: str, token: str) -> dict[str, Any]:
    return json.loads(api_bytes(path, token).decode("utf-8"))


def api_bytes(path: str, token: str) -> bytes:
    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "k8sagent-full-ci-timing",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def api_redirect_bytes(path: str, token: str) -> bytes:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self,
            request: Any,
            file_pointer: Any,
            code: int,
            message: str,
            headers: Any,
            new_url: str,
        ) -> None:
            return None

    request = urllib.request.Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "k8sagent-full-ci-timing",
        },
    )
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(request, timeout=30)
    except urllib.error.HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise
        location = exc.headers.get("Location")
        if not location:
            raise RuntimeError("artifact redirect did not include Location") from exc
    else:
        raise RuntimeError("artifact download did not redirect")
    storage_request = urllib.request.Request(
        location,
        headers={"User-Agent": "k8sagent-full-ci-timing"},
    )
    with urllib.request.urlopen(storage_request, timeout=30) as response:
        return response.read()


if __name__ == "__main__":
    raise SystemExit(main())
