#!/usr/bin/env python3
"""Analyze scaffold, patch, and e2e execution logs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ERROR_RULES = [
    {
        "type": "docker-kind-connection",
        "patterns": ["permission denied while trying to connect to the docker daemon", "cannot connect to the docker daemon", "docker daemon"],
        "cause": "Docker daemon is unavailable or the current user cannot access it.",
        "resolution": "Start Docker Desktop or Docker daemon, then confirm access with `docker ps`. If this is WSL, make sure Docker Desktop WSL integration is enabled.",
    },
    {
        "type": "kind-cluster-failure",
        "patterns": ["failed to create cluster", "no kind clusters found", "kind: command not found"],
        "cause": "The kind CLI or kind cluster setup failed.",
        "resolution": "Install kind or recreate the cluster with `kind create cluster --name <cluster-name>`.",
    },
    {
        "type": "make-not-found",
        "patterns": ["make: command not found", "no such file or directory: 'make'", "program not found: make"],
        "cause": "The `make` command is not installed or not available in PATH.",
        "resolution": "Install make, then rerun the failed command.",
    },
    {
        "type": "controller-gen-version",
        "patterns": ["controller-gen", "unknown argument", "unsupported kubebuilder", "requires controller-gen"],
        "cause": "controller-gen is missing or incompatible with the generated Kubebuilder project.",
        "resolution": "Run the project Makefile target that installs controller-gen, or align the controller-gen version with the Kubebuilder project.",
    },
    {
        "type": "envtest-missing",
        "patterns": ["envtest", "setup-envtest", "unable to start control plane", "no such file or directory.*kube-apiserver"],
        "cause": "Kubernetes envtest binaries are missing or not discoverable.",
        "resolution": "Install envtest assets with the project Makefile target or set KUBEBUILDER_ASSETS to the envtest binary directory.",
    },
    {
        "type": "crd-install-failure",
        "patterns": ["no matches for kind", "could not find the requested resource", "ensure crds are installed", "customresourcedefinition"],
        "cause": "The CRD was not installed or the API server has not registered it yet.",
        "resolution": "Run `make install`, then confirm the CRD with `kubectl get crd` before applying Custom Resources.",
    },
    {
        "type": "rbac-forbidden",
        "patterns": ["forbidden", "cannot get resource", "cannot list resource", "cannot create resource", "rbac"],
        "cause": "The controller or kubectl caller does not have the required RBAC permissions.",
        "resolution": "Add or correct RBAC markers, run `make manifests`, and redeploy or rerun the controller with updated permissions.",
    },
    {
        "type": "kubectl-apply-failure",
        "patterns": ["error from server", "the request is invalid", "strict decoding error"],
        "cause": "A manifest could not be applied to the cluster.",
        "resolution": "Inspect the YAML schema, API version, resource names, and CRD availability, then rerun `kubectl apply`.",
    },
    {
        "type": "gpu-insufficient",
        "patterns": ["insufficient nvidia.com/gpu", "nvidia.com/gpu"],
        "cause": "The Pod requested GPU resources that are not available in the cluster.",
        "resolution": "For kind-based validation, set gpuCount to 0 or treat this as an allowed warning when Job spec validation is the success criterion.",
    },
    {
        "type": "image-pull",
        "patterns": ["imagepullbackoff", "errimagepull", "failed to pull image", "pull access denied"],
        "cause": "Kubernetes could not pull the configured container image.",
        "resolution": "Check the image name, registry access, imagePullSecrets, and network connectivity.",
    },
    {
        "type": "pvc-not-found",
        "patterns": ["persistentvolumeclaim .* not found", "pvc .* not found", "persistentvolumeclaimclaim is not bound", "unbound immediate persistentvolumeclaims"],
        "cause": "The referenced PersistentVolumeClaim is missing or not bound.",
        "resolution": "Create the PVC before applying the Custom Resource, or fix spec.pvcName to reference an existing PVC.",
    },
    {
        "type": "pod-pending",
        "patterns": ["phase: pending", "unschedulable", "podscheduled"],
        "cause": "The Pod was created but could not be scheduled.",
        "resolution": "Inspect Pod events and resource requests. If the reason is GPU shortage in kind, it can be handled as a warning.",
    },
    {
        "type": "go-build-test-failure",
        "patterns": ["go test", "build failed", "undefined:", "cannot use .* as", "package .* is not in std"],
        "cause": "Go build or test failed.",
        "resolution": "Fix the referenced Go compile/test error, then rerun `make generate`, `make manifests`, and `make test` as needed.",
    },
    {
        "type": "yaml-parse-error",
        "patterns": ["yaml:", "did not find expected key", "mapping values are not allowed", "could not find expected ':'"],
        "cause": "A YAML file could not be parsed.",
        "resolution": "Fix the YAML indentation and key/value syntax, then rerun the failed step.",
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze generated execution logs and summary.json.")
    parser.add_argument("--log-dir", required=True, help="Path to a logs/scaffold, logs/patch, or logs/e2e timestamp directory.")
    parser.add_argument("--output", help="Analysis markdown path. Defaults to <log-dir>/analysis.md.")
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    if not log_dir.is_dir():
        print(f"log directory not found: {log_dir}", file=sys.stderr)
        return 2

    summary_path = log_dir / "summary.json"
    if not summary_path.is_file():
        print(f"summary.json not found under log directory: {log_dir}", file=sys.stderr)
        return 2

    summary = load_json(summary_path)
    analysis = analyze_summary(log_dir, summary)
    markdown = render_markdown(log_dir, summary_path, analysis)
    output_path = Path(args.output) if args.output else log_dir / "analysis.md"
    output_path.write_text(markdown, encoding="utf-8")

    print(f"analysis written: {output_path}")
    return 0


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"failed to parse JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"summary.json must contain an object: {path}")
    return data


def analyze_summary(log_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    failed_step_name = summary.get("failedStep")
    steps = summary.get("steps") or []
    failed_step = find_failed_step(steps, failed_step_name)
    warnings = summary.get("warnings") or []
    warning_text = "\n".join(str(item) for item in warnings)

    if failed_step_name:
        stdout = read_log(failed_step.get("stdoutLog"))
        stderr = read_log(failed_step.get("stderrLog"))
        evidence = "\n".join([stdout, stderr, warning_text])
        classifications = classify(evidence)
        primary = classifications[0] if classifications else unknown_classification()
        status = "failed"
    else:
        evidence = collect_summary_evidence(summary)
        classifications = classify("\n".join([evidence, warning_text]))
        primary = success_classification(warnings)
        status = "succeeded"

    return {
        "status": status,
        "failedStep": failed_step_name,
        "failedStepDetail": failed_step,
        "steps": steps,
        "classifications": classifications,
        "primaryClassification": primary,
        "warnings": warnings,
        "evidence": evidence,
        "recommendedCommand": recommended_command(summary, log_dir),
        "stepCounts": count_steps(steps),
        "jobSpecValidation": summary.get("jobSpecValidation"),
    }


def find_failed_step(steps: list[dict[str, Any]], failed_step_name: str | None) -> dict[str, Any]:
    if not failed_step_name:
        return {}
    for step in steps:
        if step.get("name") == failed_step_name:
            return step
    for step in steps:
        if step.get("status") == "failed":
            return step
    return {"name": failed_step_name}


def read_log(value: Any) -> str:
    if not value:
        return ""
    path = Path(str(value))
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def collect_summary_evidence(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    for step in summary.get("steps") or []:
        command = " ".join(str(part) for part in step.get("command") or [])
        lines.append(
            f"{step.get('name', '<unnamed>')}: status={step.get('status', '<unknown>')} "
            f"exitCode={step.get('exitCode')} command={command}"
        )
    warnings = summary.get("warnings") or []
    for warning in warnings:
        lines.append(f"warning: {warning}")
    validation = summary.get("jobSpecValidation")
    if isinstance(validation, dict):
        lines.append(f"jobSpecValidation.passed={validation.get('passed')}")
        for item in validation.get("checks") or []:
            lines.append(
                f"jobSpecValidation.{item.get('name', 'unknown')}: "
                f"status={item.get('status')} expected={item.get('expected')} actual={item.get('actual')}"
            )
    return "\n".join(lines)


def classify(text: str) -> list[dict[str, str]]:
    lowered = text.lower()
    matches = []
    for rule in ERROR_RULES:
        for pattern in rule["patterns"]:
            if re.search(pattern, lowered, re.IGNORECASE):
                matches.append(
                    {
                        "type": rule["type"],
                        "cause": rule["cause"],
                        "resolution": rule["resolution"],
                    }
                )
                break
    return unique_classifications(matches)


def unique_classifications(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    result = []
    for item in items:
        key = item["type"]
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def unknown_classification() -> dict[str, str]:
    return {
        "type": "unknown",
        "cause": "The log did not match a known failure pattern.",
        "resolution": "Inspect the failed step stdout/stderr logs and add a new analyzer rule if this is a recurring error.",
    }


def success_classification(warnings: list[Any]) -> dict[str, str]:
    if any("gpu" in str(item).lower() for item in warnings):
        return {
            "type": "succeeded-with-warning",
            "cause": "The run succeeded, but a GPU-related Pod Pending warning was recorded.",
            "resolution": "No fix is required for kind e2e when Job spec validation passed. Use gpuCount 0 for a fully schedulable sample.",
        }
    return {
        "type": "succeeded",
        "cause": "All required steps completed successfully.",
        "resolution": "No corrective action is required.",
    }


def count_steps(steps: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"total": len(steps), "succeeded": 0, "failed": 0, "skipped": 0, "running": 0}
    for step in steps:
        status = str(step.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def recommended_command(summary: dict[str, Any], log_dir: Path) -> str:
    if "clusterName" in summary or "context" in summary:
        command = ["python3", "agent/tools/e2e_runner.py"]
        input_path = summary.get("input")
        profile_path = nested_get(summary, ["profileConfig", "profilePath"])
        if not profile_path:
            return insufficient_rerun_info()
        if input_path:
            command.extend(["--input", str(input_path)])
        else:
            project = summary.get("projectDir")
            cluster = summary.get("clusterName")
            sample = summary.get("sample")
            if not (project and cluster and sample):
                return insufficient_rerun_info()
            command.extend(["--project", str(project), "--cluster-name", str(cluster), "--sample", str(sample)])
        command.extend(["--profile", str(profile_path)])
        if summary.get("clean"):
            command.append("--clean")
        if summary.get("deletePvc"):
            command.append("--delete-pvc")
        if summary.get("skipPvc"):
            command.append("--skip-pvc")
        command.append("--execute")
        return shell_join(command)

    if "targetDir" in summary or "workspace" in summary:
        input_path = summary.get("input")
        workspace = summary.get("workspace")
        if not (input_path and workspace):
            return insufficient_rerun_info()
        command = ["python3", "agent/tools/scaffold_runner.py", "--input", str(input_path), "--workspace", str(workspace)]
        if summary.get("force"):
            command.append("--force")
        command.append("--execute")
        return shell_join(command)

    if "projectDir" in summary:
        input_path = summary.get("input")
        project = summary.get("projectDir")
        profile_path = nested_get(summary, ["profile", "path"])
        if not (input_path and project):
            return insufficient_rerun_info()
        command = ["python3", "agent/tools/artifact_patcher.py", "--input", str(input_path), "--project", str(project)]
        if profile_path:
            command.extend(["--profile", str(profile_path)])
        command.append("--execute")
        return shell_join(command)

    return insufficient_rerun_info()


def nested_get(data: dict[str, Any], keys: list[str]) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def insufficient_rerun_info() -> str:
    return "summary.json에 재실행 명령을 구성할 충분한 정보가 없어, 동일 runner 명령을 수동으로 확인해야 한다."


def shell_join(parts: list[str]) -> str:
    return " ".join(shell_quote(part) for part in parts)


def shell_quote(value: Any) -> str:
    text = str(value)
    if not text:
        return "''"
    if re.search(r"[^A-Za-z0-9_@%+=:,./-]", text):
        return "'" + text.replace("'", "'\"'\"'") + "'"
    return text


def render_markdown(log_dir: Path, summary_path: Path, analysis: dict[str, Any]) -> str:
    status = analysis["status"]
    failed_step = analysis["failedStep"] or "none"
    primary = analysis["primaryClassification"]
    lines = [
        "# Log Analysis",
        "",
        "## Overall Result",
        f"- Log directory: `{log_dir}`",
        f"- Summary file: `{summary_path}`",
        f"- Status: `{status}`",
        f"- Failed step: `{failed_step}`",
        "",
        "## Step Summary",
    ]
    counts = analysis["stepCounts"]
    for key in ("total", "succeeded", "failed", "skipped", "running"):
        lines.append(f"- {key}: {counts.get(key, 0)}")

    lines.extend(render_steps(analysis.get("steps") or []))

    lines.extend(
        [
            "",
            "## Error Type",
            f"- Primary type: `{primary['type']}`",
            f"- Cause: {primary['cause']}",
            f"- Resolution: {primary['resolution']}",
        ]
    )

    related = [item for item in analysis["classifications"] if item["type"] != primary["type"]]
    if related:
        lines.extend(["", "## Related Signals"])
        for item in related:
            lines.append(f"- `{item['type']}`: {item['cause']}")

    warnings = analysis["warnings"]
    lines.extend(["", "## Warnings"])
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")

    lines.extend(render_job_spec_validation(analysis.get("jobSpecValidation")))

    lines.extend(
        [
            "",
            "## Evidence Log Summary",
            summarize_evidence(analysis["evidence"]),
            "",
            "## Recommended Re-run",
            "```bash",
            analysis["recommendedCommand"],
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def render_job_spec_validation(validation: Any) -> list[str]:
    lines = ["", "## Job Spec Validation"]
    if not isinstance(validation, dict):
        lines.append("- not recorded")
        return lines

    lines.append(f"- passed: `{str(validation.get('passed')).lower()}`")
    checks = validation.get("checks") or []
    for item in checks:
        name = item.get("name", "unknown")
        expected = item.get("expected", "")
        actual = item.get("actual", "")
        status = item.get("status", "unknown")
        lines.append(f"- {name}: `{status}` (expected `{expected}`, actual `{actual}`)")
    return lines


def render_steps(steps: list[dict[str, Any]]) -> list[str]:
    if not steps:
        return ["", "## Steps", "- not recorded"]
    lines = [
        "",
        "## Steps",
        "| # | Step | Status | Exit Code | Command |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, step in enumerate(steps, start=1):
        command = " ".join(str(part) for part in step.get("command") or [])
        lines.append(
            f"| {index} | `{step.get('name', '')}` | `{step.get('status', '')}` | "
            f"`{step.get('exitCode')}` | `{command}` |"
        )
    return lines


def summarize_evidence(text: str) -> str:
    clean = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    if not clean:
        return "- No stdout/stderr evidence was available."
    lines = clean.splitlines()
    selected = lines[:40]
    if len(lines) > 40:
        selected.append(f"... truncated {len(lines) - 40} additional lines ...")
    return "```text\n" + "\n".join(selected) + "\n```"


if __name__ == "__main__":
    raise SystemExit(main())
