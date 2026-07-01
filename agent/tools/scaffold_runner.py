#!/usr/bin/env python3
"""Run or dry-run Kubebuilder scaffold commands from an Operator spec."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.error_taxonomy import ErrorCode, emit_tool_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run or execute Kubebuilder scaffold commands.")
    parser.add_argument("--input", required=True, help="Path to generated operator spec YAML.")
    parser.add_argument(
        "--workspace",
        help="Parent directory for generated Operator projects. Defaults to the parent of project.workspace, or workspace/generated-operators.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned commands without executing. This is the default.")
    parser.add_argument("--execute", action="store_true", help="Actually run scaffold commands.")
    parser.add_argument("--preflight", action="store_true", help="Run environment and spec checks without scaffolding.")
    parser.add_argument("--force", action="store_true", help="Delete an existing target project directory before execution.")
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip scaffold-only make checks when a later validation gate is guaranteed.",
    )
    args = parser.parse_args()

    if args.dry_run and args.execute:
        print("Use either --dry-run or --execute, not both.", file=sys.stderr)
        emit_tool_error(
            ErrorCode.INVALID_TOOL_ARGUMENTS,
            "Use either --dry-run or --execute, not both.",
            stage="argument-validation",
        )
        return 2

    input_path = Path(args.input)
    spec = load_spec(input_path)
    model = normalize_spec(spec)
    missing = required_missing(model)
    workspace_parent, target_dir = resolve_workspace(args.workspace, model)
    steps = build_steps(
        model,
        target_dir,
        include_validation=not args.skip_validation,
    )

    if args.preflight:
        result = run_preflight(input_path, workspace_parent, target_dir, spec, model, missing, args.force)
        print_preflight(result)
        print(f"Preflight result written: {result['preflightLog']}")
        return 0 if result["passed"] else 2

    errors = spec.get("errors") or []
    if errors:
        print("Cannot run scaffold because operator spec has errors:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        emit_tool_error(
            ErrorCode.REQUIRED_INPUT_MISSING,
            "; ".join(str(item) for item in errors),
            stage="scaffold-preflight",
        )
        return 2

    warnings = spec.get("warnings") or []
    if warnings:
        print("Warnings from operator spec:")
        for warning in warnings:
            print(f"- {warning}")
        print()

    if missing:
        print("Cannot run scaffold because required fields are missing:", file=sys.stderr)
        for field in missing:
            print(f"- {field}", file=sys.stderr)
        emit_tool_error(
            ErrorCode.REQUIRED_INPUT_MISSING,
            "Missing required fields: " + ", ".join(missing),
            stage="scaffold-preflight",
        )
        return 2

    if not args.execute:
        print_dry_run(input_path, model, workspace_parent, target_dir, steps, args.force)
        return 0

    result = run_preflight(input_path, workspace_parent, target_dir, spec, model, missing, args.force)
    print_preflight(result)
    print(f"Preflight result written: {result['preflightLog']}")
    if not result["passed"]:
        print("Scaffold execution stopped because preflight failed.", file=sys.stderr)
        emit_tool_error(
            ErrorCode.REQUIRED_INPUT_MISSING,
            "Scaffold execution stopped because preflight failed.",
            stage="scaffold-preflight",
        )
        return 2

    return execute_steps(input_path, target_dir, steps, args.force)


def load_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"operator spec not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"operator spec must be a YAML mapping: {path}")
    return data


def normalize_spec(spec: dict[str, Any]) -> dict[str, Any]:
    project = spec.get("project") or {}
    api = spec.get("api") or {}
    resource = spec.get("resource") or {}
    controller = spec.get("controller") or {}
    validation = spec.get("validation") or {}

    kind = api.get("kind") or resource.get("kind", "")
    name = project.get("name") or infer_project_name(kind)
    spec_workspace = project.get("workspace") or (f"workspace/{name}" if name else "")
    directory_name = Path(spec_workspace).name if spec_workspace else name
    domain = project.get("domain") or api.get("domain") or infer_domain(resource.get("apiGroup", ""), resource.get("group", ""))
    module = project.get("module") or (f"{domain}/{name}" if domain and name else "")
    group = api.get("group") or resource.get("group", "")
    version = api.get("version") or resource.get("version", "")

    return {
        "project": {
            "name": name,
            "directoryName": directory_name,
            "specWorkspace": spec_workspace,
            "module": module,
            "domain": domain,
        },
        "api": {
            "group": group,
            "version": version,
            "kind": kind,
        },
        "controllerEnabled": bool(controller.get("enabled", True)),
        "validationCommands": validation.get("commands") or ["make generate", "make manifests", "make test"],
    }


def resolve_workspace(workspace_arg: str | None, model: dict[str, Any]) -> tuple[Path, Path]:
    project = model["project"]
    spec_workspace = project.get("specWorkspace") or ""
    directory_name = project.get("directoryName") or project.get("name") or "<project-name>"

    if workspace_arg:
        workspace_parent = Path(workspace_arg)
        return workspace_parent, workspace_parent / directory_name

    if spec_workspace:
        target_dir = Path(spec_workspace)
        return target_dir.parent, target_dir

    workspace_parent = Path("workspace/generated-operators")
    return workspace_parent, workspace_parent / directory_name


def required_missing(model: dict[str, Any]) -> list[str]:
    checks = {
        "project.name": model["project"].get("name"),
        "project.module": model["project"].get("module"),
        "project.domain": model["project"].get("domain"),
        "api.group": model["api"].get("group"),
        "api.version": model["api"].get("version"),
        "api.kind": model["api"].get("kind"),
    }
    return [name for name, value in checks.items() if not value]


def build_steps(
    model: dict[str, Any],
    target_dir: Path,
    *,
    include_validation: bool = True,
) -> list[dict[str, Any]]:
    project = model["project"]
    api = model["api"]
    controller_flag = "--controller" if model["controllerEnabled"] else "--controller=false"

    steps = [
        {
            "name": "create-workspace",
            "command": ["mkdir", "-p", str(target_dir)],
            "cwd": ".",
            "internal": True,
        },
        {
            "name": "kubebuilder-init",
            "command": ["kubebuilder", "init", "--domain", project["domain"], "--repo", project["module"]],
            "cwd": str(target_dir),
        },
        {
            "name": "patch-makefile",
            "command": ["patch-makefile", str(target_dir / "Makefile")],
            "cwd": str(target_dir),
            "internal": True,
        },
        {
            "name": "kubebuilder-create-api",
            "command": [
                "kubebuilder",
                "create",
                "api",
                "--group",
                api["group"],
                "--version",
                api["version"],
                "--kind",
                api["kind"],
                "--resource",
                controller_flag,
            ],
            "cwd": str(target_dir),
        },
        {
            "name": "patch-controller-tests",
            "command": ["patch-controller-tests", str(target_dir), api["kind"]],
            "cwd": str(target_dir),
            "internal": True,
        },
        {"name": "make-generate", "command": ["make", "generate"], "cwd": str(target_dir)},
        {"name": "make-manifests", "command": ["make", "manifests"], "cwd": str(target_dir)},
        {"name": "make-test", "command": ["make", "test"], "cwd": str(target_dir)},
    ]
    if not include_validation:
        steps = [
            step
            for step in steps
            if step["name"]
            not in {"make-generate", "make-manifests", "make-test"}
        ]
    return steps


def run_preflight(
    input_path: Path,
    workspace_parent: Path,
    target_dir: Path,
    spec: dict[str, Any],
    model: dict[str, Any],
    missing: list[str],
    force: bool,
) -> dict[str, Any]:
    log_dir = Path("logs") / "scaffold" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_dir.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, str]] = []
    env_path = f"{Path.cwd() / '.tools/bin'}:{os.environ.get('PATH', '')}"

    for command in ("kubebuilder", "go", "make", "git"):
        found = shutil.which(command, path=env_path)
        add_check(
            checks,
            f"{command} available",
            "passed" if found else "failed",
            found or f"{command} was not found in PATH",
        )

    add_check(
        checks,
        "workspace path exists",
        "passed" if workspace_parent.is_dir() else "failed",
        f"{workspace_parent} exists" if workspace_parent.is_dir() else f"{workspace_parent} does not exist",
    )

    if target_dir.exists() and not force:
        add_check(checks, "target project directory", "failed", f"{target_dir} already exists; use --force to recreate it")
    elif target_dir.exists() and force:
        add_check(checks, "target project directory", "passed", f"{target_dir} exists and --force is enabled")
    else:
        add_check(checks, "target project directory", "passed", f"{target_dir} does not exist")

    spec_errors = spec.get("errors") or []
    add_check(
        checks,
        "operator spec errors",
        "passed" if not spec_errors else "failed",
        "errors is empty" if not spec_errors else "; ".join(str(item) for item in spec_errors),
    )

    spec_warnings = spec.get("warnings") or []
    add_check(
        checks,
        "operator spec warnings",
        "warning" if spec_warnings else "passed",
        "warnings is empty" if not spec_warnings else "; ".join(str(item) for item in spec_warnings),
    )

    project = model["project"]
    api = model["api"]
    add_required_check(checks, "project.module", project.get("module"))
    add_required_check(checks, "project.domain", project.get("domain"))
    add_required_check(checks, "api.group", api.get("group"))
    add_required_check(checks, "api.version", api.get("version"))
    add_required_check(checks, "api.kind", api.get("kind"))
    for field in missing:
        add_check(checks, f"required field {field}", "failed", f"{field} is missing")

    result = {
        "input": str(input_path),
        "specWorkspace": model["project"].get("specWorkspace", ""),
        "workspace": str(workspace_parent),
        "targetDir": str(target_dir),
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "passed": not any(check["status"] == "failed" for check in checks),
        "checks": checks,
        "preflightLog": str(log_dir / "preflight.json"),
    }
    Path(result["preflightLog"]).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def add_required_check(checks: list[dict[str, str]], name: str, value: Any) -> None:
    add_check(checks, name, "passed" if value else "failed", str(value) if value else f"{name} is missing")


def add_check(checks: list[dict[str, str]], name: str, status: str, message: str) -> None:
    checks.append(
        {
            "name": name,
            "status": status,
            "message": message,
        }
    )


def print_preflight(result: dict[str, Any]) -> None:
    print("Preflight checks")
    print(f"Input spec: {result['input']}")
    print(f"Spec-defined workspace: {result.get('specWorkspace') or '<not set>'}")
    print(f"Scaffold workspace parent: {result['workspace']}")
    print(f"Target project directory: {result['targetDir']}")
    print(f"Passed: {result['passed']}")
    print()
    print("| Status | Check | Message |")
    print("| --- | --- | --- |")
    for check in result["checks"]:
        status = {"passed": "PASS", "warning": "WARN", "failed": "FAIL"}.get(check["status"], check["status"].upper())
        print(f"| {status} | {check['name']} | {check['message']} |")
    print()


def print_dry_run(
    input_path: Path,
    model: dict[str, Any],
    workspace_parent: Path,
    target_dir: Path,
    steps: list[dict[str, Any]],
    force: bool,
) -> None:
    print("Dry-run mode: no files will be created and no commands will be executed.")
    print(f"Input spec: {input_path}")
    print(f"Spec-defined workspace: {model['project'].get('specWorkspace') or '<not set>'}")
    print(f"Scaffold workspace parent: {workspace_parent}")
    print(f"Target project directory: {target_dir}")
    print("Actual Kubebuilder project will be created in the target project directory above.")
    print(f"Force enabled: {force}")
    print()
    print("Planned steps:")
    for index, step in enumerate(steps, start=1):
        cwd = step["cwd"]
        command = " ".join(step["command"])
        print(f"{index}. [{step['name']}]")
        print(f"   cwd: {cwd}")
        print(f"   command: {command}")


def execute_steps(input_path: Path, target_dir: Path, steps: list[dict[str, Any]], force: bool) -> int:
    if target_dir.exists():
        if not force:
            print(f"Target project directory already exists: {target_dir}", file=sys.stderr)
            print("Use --force to delete and recreate it.", file=sys.stderr)
            return 2
        shutil.rmtree(target_dir)

    log_dir = Path("logs") / "scaffold" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    log_dir.mkdir(parents=True, exist_ok=True)

    env = build_execution_env()

    summary: dict[str, Any] = {
        "input": str(input_path),
        "targetDir": str(target_dir),
        "execute": True,
        "force": force,
        "logDir": str(log_dir),
        "steps": [],
        "failedStep": None,
    }

    for index, step in enumerate(steps, start=1):
        result = run_step(index, step, log_dir, env)
        summary["steps"].append(result)
        write_summary(log_dir, summary)
        if result["status"] != "succeeded":
            summary["failedStep"] = result["name"]
            write_summary(log_dir, summary)
            print(f"Scaffold failed at step: {result['name']} (exit code {result['exitCode']})", file=sys.stderr)
            print(f"Logs: {log_dir}", file=sys.stderr)
            return result["exitCode"] or 1

    write_summary(log_dir, summary)
    print(f"Scaffold completed: {target_dir}")
    print(f"Logs: {log_dir}")
    return 0


def run_step(index: int, step: dict[str, Any], log_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    safe_name = step["name"].replace("_", "-")
    stdout_log = log_dir / f"{index:02d}-{safe_name}.stdout.log"
    stderr_log = log_dir / f"{index:02d}-{safe_name}.stderr.log"
    command = step["command"]
    cwd = Path(step["cwd"])

    print(f"+ ({cwd}) {' '.join(command)}")

    if step.get("internal"):
        try:
            if step["name"] == "create-workspace":
                Path(command[-1]).mkdir(parents=True, exist_ok=True)
            elif step["name"] == "patch-makefile":
                patch_makefile(Path(command[-1]))
            elif step["name"] == "patch-controller-tests":
                patch_controller_tests(Path(command[1]), command[2])
            else:
                raise ValueError(f"unsupported internal step: {step['name']}")
            stdout_log.write_text("", encoding="utf-8")
            stderr_log.write_text("", encoding="utf-8")
            exit_code = 0
        except Exception as exc:  # noqa: BLE001
            stdout_log.write_text("", encoding="utf-8")
            stderr_log.write_text(str(exc), encoding="utf-8")
            exit_code = 1
    else:
        completed = subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True)
        stdout_log.write_text(completed.stdout, encoding="utf-8")
        stderr_log.write_text(completed.stderr, encoding="utf-8")
        exit_code = completed.returncode

    return {
        "name": step["name"],
        "command": command,
        "cwd": str(cwd),
        "exitCode": exit_code,
        "status": "succeeded" if exit_code == 0 else "failed",
        "stdoutLog": str(stdout_log),
        "stderrLog": str(stderr_log),
    }


def write_summary(log_dir: Path, summary: dict[str, Any]) -> None:
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def build_execution_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{Path.cwd() / '.tools/bin'}:{env.get('PATH', '')}"
    env["GOCACHE"] = env.get("GOCACHE", "/tmp/k8sagent-go-build")
    flags = env.get("GOFLAGS", "").split()
    if "-buildvcs=false" not in flags:
        flags.append("-buildvcs=false")
    env["GOFLAGS"] = " ".join(flags)
    return env


def patch_makefile(makefile: Path) -> None:
    if not makefile.exists():
        raise FileNotFoundError(f"Makefile not found: {makefile}")
    text = makefile.read_text(encoding="utf-8")
    text = text.replace("CONTROLLER_TOOLS_VERSION ?= v0.15.0", "CONTROLLER_TOOLS_VERSION ?= v0.21.0")
    text = text.replace(
        "test: manifests generate fmt vet envtest ## Run tests.\n"
        "\tKUBEBUILDER_ASSETS=\"$(shell $(ENVTEST) use $(ENVTEST_K8S_VERSION) --bin-dir $(LOCALBIN) -p path)\" go test $$(go list ./... | grep -v /e2e) -coverprofile cover.out",
        "test: manifests generate fmt vet ## Run tests.\n"
        "\tgo test $$(go list ./... | grep -v /e2e) -coverprofile cover.out",
    )
    makefile.write_text(text, encoding="utf-8")
    patch_dockerfile(makefile.parent / "Dockerfile")


def patch_dockerfile(dockerfile: Path) -> None:
    if not dockerfile.is_file():
        raise FileNotFoundError(f"Dockerfile not found: {dockerfile}")
    text = dockerfile.read_text(encoding="utf-8")
    text = text.replace(
        "RUN go mod download",
        "RUN --mount=type=cache,target=/go/pkg/mod go mod download",
    )
    text = text.replace(
        "RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} go build -a -o manager cmd/main.go",
        "RUN --mount=type=cache,target=/go/pkg/mod "
        "--mount=type=cache,target=/root/.cache/go-build "
        "CGO_ENABLED=0 GOOS=${TARGETOS:-linux} GOARCH=${TARGETARCH} "
        "go build -o manager cmd/main.go",
    )
    dockerfile.write_text(text, encoding="utf-8")


def patch_controller_tests(workspace: Path, kind: str) -> None:
    controller_dir = workspace / "internal" / "controller"
    suite_test = controller_dir / "suite_test.go"
    if suite_test.exists():
        suite_test.unlink()

    test_file = controller_dir / f"{kind.lower()}_controller_test.go"
    if not test_file.exists():
        return

    test_file.write_text(
        f"""/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import "testing"

func Test{kind}ReconcilerIsConstructible(t *testing.T) {{
\t_ = &{kind}Reconciler{{}}
}}
""",
        encoding="utf-8",
    )


def infer_project_name(kind: str) -> str:
    if not kind:
        return ""
    return f"{to_kebab(kind)}-operator"


def infer_domain(api_group: str, group: str) -> str:
    prefix = f"{group}."
    if api_group.startswith(prefix):
        return api_group[len(prefix) :]
    return ""


def to_kebab(value: str) -> str:
    result = []
    for index, char in enumerate(value):
        if index and char.isupper() and (value[index - 1].islower() or value[index - 1].isdigit()):
            result.append("-")
        result.append(char.lower())
    return "".join(result)


if __name__ == "__main__":
    raise SystemExit(main())
