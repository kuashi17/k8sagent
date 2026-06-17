#!/usr/bin/env python3
"""Evaluate MVP proposal metrics from real Agent execution logs."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.agent_log_collector import collect_logs
from agent.evaluation.artifact_checker import check_record
from agent.evaluation.mvp_report_generator import write_report


DEFAULT_BASELINE = REPO_ROOT / "evaluation" / "mvp-baseline.yaml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "evaluation" / "results" / "mvp"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate MVP metrics from Agent logs.")
    parser.add_argument("--logs-dir", default="logs/agent")
    parser.add_argument("--log-paths", nargs="*")
    parser.add_argument("--baseline", default=str(DEFAULT_BASELINE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    baseline = load_yaml(resolve_path(args.baseline))
    records = [record.to_dict() for record in collect_logs(args.logs_dir, args.log_paths)]
    output_dir = resolve_path(args.output_dir) / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    artifact_results = [check_record(record) for record in records]
    validation_results = [validation_result(record) for record in records]
    error_results = [error_response_result(record) for record in records if record.get("failureContext")]
    details = {
        "logs": records,
        "artifactCompletion": artifact_results,
        "validationPass": validation_results,
        "errorResponse": error_results,
    }
    summary = build_summary(records, artifact_results, validation_results, error_results, baseline)

    write_json(output_dir / "mvp-evaluation-summary.json", summary)
    write_json(output_dir / "mvp-evaluation-details.json", details)
    write_json(output_dir / "artifact-completion-results.json", artifact_results)
    write_json(output_dir / "validation-pass-results.json", validation_results)
    write_json(output_dir / "error-response-results.json", error_results)
    write_report(output_dir / "mvp-evaluation-report.md", summary, details)
    print(f"MVP evaluation written: {output_dir}")
    print(json.dumps(summary.get("metrics", {}), indent=2, ensure_ascii=False))
    return 0


def build_summary(
    records: list[dict[str, Any]],
    artifact_results: list[dict[str, Any]],
    validation_results: list[dict[str, Any]],
    error_results: list[dict[str, Any]],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    targets = baseline.get("targets") or {}
    baseline_data = baseline.get("manualBaseline") or {}
    return {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "evaluatedLogCount": len(records),
        "evaluatedLogs": [record.get("path") for record in records],
        "baseline": baseline_data,
        "targets": targets,
        "metrics": {
            "timeReduction": time_reduction_metric(records, baseline_data, targets),
            "artifactCompletion": artifact_completion_metric(artifact_results, targets),
            "firstPassValidation": validation_pass_metric(validation_results, targets),
            "errorResponse": error_response_metric(error_results, targets),
        },
    }


def time_reduction_metric(records: list[dict[str, Any]], baseline: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    execute_records = [record for record in records if record.get("mode") == "requirement-planning" and record.get("agentMode") == "execute"]
    elapsed_values = [float(record["elapsedSeconds"]) for record in execute_records if record.get("elapsedSeconds") is not None]
    baseline_minutes = baseline.get("requirementToArtifactsMinutes")
    measured = bool(baseline.get("measured"))
    if not elapsed_values or not baseline_minutes or not measured:
        return {
            "target": targets.get("timeReductionPercent"),
            "targetDisplay": f"{targets.get('timeReductionPercent')}%",
            "result": None,
            "resultDisplay": "측정 데이터 부족",
            "status": "측정 불가",
            "evidence": "baseline measured=false 또는 execute elapsed 데이터 부족",
        }
    average_seconds = statistics.mean(elapsed_values)
    baseline_seconds = float(baseline_minutes) * 60
    reduction = max(0.0, (baseline_seconds - average_seconds) / baseline_seconds * 100)
    target = float(targets.get("timeReductionPercent") or 0)
    return {
        "target": target,
        "targetDisplay": f"{target:g}%",
        "result": round(reduction, 2),
        "resultDisplay": f"{round(reduction, 2)}%",
        "status": "달성" if reduction >= target else "미달성",
        "evidence": f"execute logs={len(execute_records)}, avgElapsedSeconds={round(average_seconds, 3)}, baselineMinutes={baseline_minutes}",
    }


def artifact_completion_metric(results: list[dict[str, Any]], targets: dict[str, Any]) -> dict[str, Any]:
    executable = [
        item
        for item in results
        if item.get("applicable")
        and item.get("mode") == "requirement-planning"
        and item.get("agentMode") == "execute"
        and item.get("projectDir")
        and "missing" not in str(item.get("projectDir"))
    ]
    values = [float(item.get("completionPercent") or 0.0) for item in executable]
    if not values:
        return no_data_metric(targets.get("artifactCompletionPercent"), "%", "artifact logs 부족")
    average = statistics.mean(values)
    target = float(targets.get("artifactCompletionPercent") or 0)
    return {
        "target": target,
        "targetDisplay": f"{target:g}%",
        "result": round(average, 2),
        "resultDisplay": f"{round(average, 2)}%",
        "status": "달성" if average >= target else "미달성",
        "evidence": f"artifact logs={len(values)}, requiredArtifacts=9",
    }


def validation_pass_metric(results: list[dict[str, Any]], targets: dict[str, Any]) -> dict[str, Any]:
    measured = []
    for item in results:
        for step in (item.get("results") or {}).values():
            if step.get("firstAttempt") in {"succeeded", "failed"}:
                measured.append(step["firstAttempt"] == "succeeded")
    if not measured:
        return no_data_metric(targets.get("firstPassValidationPercent"), "%", "validation 결과 부족")
    percent = sum(1 for value in measured if value) / len(measured) * 100
    target = float(targets.get("firstPassValidationPercent") or 0)
    return {
        "target": target,
        "targetDisplay": f"{target:g}%",
        "result": round(percent, 2),
        "resultDisplay": f"{round(percent, 2)}%",
        "status": "달성" if percent >= target else "미달성",
        "evidence": f"measuredSteps={len(measured)}",
    }


def error_response_metric(results: list[dict[str, Any]], targets: dict[str, Any]) -> dict[str, Any]:
    values = [float(item["responseSeconds"]) for item in results if item.get("responseSeconds") is not None]
    target_minutes = float(targets.get("errorResponseMinutes") or 0)
    if not values:
        return no_data_metric(target_minutes, "분", "failure/recovery 로그 부족")
    average = statistics.mean(values)
    p95 = percentile(values, 0.95)
    target_seconds = target_minutes * 60
    return {
        "target": target_minutes,
        "targetDisplay": f"{target_minutes:g}분 이내",
        "result": round(average / 60, 3),
        "resultDisplay": f"avg {round(average / 60, 3)}분 / p95 {round(p95 / 60, 3)}분",
        "averageSeconds": round(average, 3),
        "p95Seconds": round(p95, 3),
        "status": "달성" if average <= target_seconds and p95 <= target_seconds else "미달성",
        "evidence": f"failure logs={len(values)}",
    }


def validation_result(record: dict[str, Any]) -> dict[str, Any]:
    results = {
        "makeGenerate": {"firstAttempt": "not-measured", "attemptCount": 0},
        "makeManifests": {"firstAttempt": "not-measured", "attemptCount": 0},
        "makeTest": {"firstAttempt": "not-measured", "attemptCount": 0},
        "build": {"firstAttempt": "not-measured", "attemptCount": 0},
        "e2e": {"firstAttempt": "not-measured", "attemptCount": 0},
    }
    for tool in record.get("toolResults") or []:
        if tool.get("tool") == "validation":
            for step in tool.get("steps") or []:
                target = step.get("target")
                key = {"generate": "makeGenerate", "manifests": "makeManifests", "test": "makeTest", "build": "build"}.get(target)
                if key and results[key]["attemptCount"] == 0:
                    results[key] = {
                        "firstAttempt": "succeeded" if step.get("exitCode") == 0 else "failed",
                        "attemptCount": 1,
                        "exitCode": step.get("exitCode"),
                    }
        if tool.get("tool") == "e2e_runner" and results["e2e"]["attemptCount"] == 0:
            results["e2e"] = {
                "firstAttempt": "succeeded" if tool.get("exitCode") == 0 else "failed",
                "attemptCount": 1,
                "exitCode": tool.get("exitCode"),
            }
    return {"logPath": record.get("path"), "results": results}


def error_response_result(record: dict[str, Any]) -> dict[str, Any]:
    failure = record.get("failureContext") or {}
    recovery = record.get("recoveryPlan") or {}
    # Existing logs do not store per-event timestamps yet, so use whole failed Agent
    # run elapsed as an upper-bound for failure-to-recovery response time.
    return {
        "logPath": record.get("path"),
        "failedTool": failure.get("failedTool"),
        "failedStep": failure.get("failedStep"),
        "exitCode": failure.get("exitCode"),
        "recoveryPlanStatus": recovery.get("status") or ("waiting-for-user-approval" if recovery else ""),
        "classification": recovery.get("classification"),
        "responseSeconds": record.get("elapsedSeconds"),
        "measurementBasis": "agent run elapsed upper-bound; per-event timestamps not present in existing logs",
    }


def no_data_metric(target: Any, unit: str, evidence: str) -> dict[str, Any]:
    return {
        "target": target,
        "targetDisplay": f"{target}{unit}" if target is not None else "-",
        "result": None,
        "resultDisplay": "측정 데이터 부족",
        "status": "측정 불가",
        "evidence": evidence,
    }


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * p
    lower = int(pos)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (pos - lower)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else REPO_ROOT / value


if __name__ == "__main__":
    raise SystemExit(main())
