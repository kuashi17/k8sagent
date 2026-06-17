#!/usr/bin/env python3
"""Check required Kubebuilder Agent artifacts on disk."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ARTIFACTS = [
    "operatorSpec",
    "commandPlan",
    "apiTypes",
    "controller",
    "crdManifest",
    "rbacManifest",
    "sampleCustomResource",
    "makefile",
    "testOrMakeTest",
]


def check_record(record: dict[str, Any]) -> dict[str, Any]:
    generated = record.get("generatedFiles") or {}
    applicable = bool(generated.get("operatorSpec") or generated.get("commandPlan") or record.get("failureContext"))
    spec_path = resolve_path(generated.get("operatorSpec") or "")
    command_plan = resolve_path(generated.get("commandPlan") or "")
    spec = load_yaml(spec_path) if spec_path.is_file() else {}
    project_dir = infer_project_dir(record, spec)
    kind = ((spec.get("api") or {}).get("kind") or "").lower()
    version = (spec.get("api") or {}).get("version") or "v1alpha1"
    group = (spec.get("api") or {}).get("group") or ""

    checks = {
        "operatorSpec": check_yaml_file(spec_path, lambda data: bool((data.get("api") or {}).get("kind")), "operator spec YAML with api.kind"),
        "commandPlan": check_nonempty_file(command_plan, "command plan Markdown"),
        "apiTypes": check_nonempty_file(project_dir / "api" / version / f"{kind}_types.go", "API type Go file") if kind else missing("API type Go file"),
        "controller": check_controller(project_dir, kind),
        "crdManifest": check_crd(project_dir, group, version, kind),
        "rbacManifest": check_rbac(project_dir),
        "sampleCustomResource": check_sample(project_dir, group, version, (spec.get("api") or {}).get("kind") or ""),
        "makefile": check_nonempty_file(project_dir / "Makefile", "Kubebuilder Makefile"),
        "testOrMakeTest": check_test_or_make_result(record, project_dir),
    }
    present = sum(1 for item in checks.values() if item["exists"] and item["valid"])
    return {
        "logPath": record.get("path"),
        "mode": record.get("mode"),
        "agentMode": record.get("agentMode"),
        "applicable": applicable,
        "projectDir": rel(project_dir),
        "kind": (spec.get("api") or {}).get("kind") or "",
        "checks": checks,
        "presentValidCount": present,
        "requiredCount": len(REQUIRED_ARTIFACTS),
        "completionPercent": round(present / len(REQUIRED_ARTIFACTS) * 100, 2),
    }


def infer_project_dir(record: dict[str, Any], spec: dict[str, Any]) -> Path:
    failure = record.get("failureContext") or {}
    if failure.get("targetProjectDir"):
        return resolve_path(failure["targetProjectDir"])
    for result in record.get("toolResults") or []:
        if result.get("tool") == "artifact_patcher":
            command = result.get("command") or []
            if "--project" in command:
                index = command.index("--project")
                if index + 1 < len(command):
                    return resolve_path(command[index + 1])
        if result.get("tool") == "scaffold_runner":
            command = result.get("command") or []
            if "--workspace" in command:
                index = command.index("--workspace")
                project_name = (spec.get("project") or {}).get("name") or ""
                if index + 1 < len(command) and project_name:
                    return resolve_path(command[index + 1]) / project_name
    workspace = (spec.get("project") or {}).get("workspace")
    if workspace:
        return resolve_path(workspace)
    project_name = (spec.get("project") or {}).get("name") or ""
    return REPO_ROOT / "workspace" / "generated-operators" / project_name


def check_controller(project_dir: Path, kind: str) -> dict[str, Any]:
    candidates = [
        project_dir / "internal" / "controller" / f"{kind}_controller.go",
        project_dir / "controllers" / f"{kind}_controller.go",
    ]
    for path in candidates:
        result = check_nonempty_file(path, "Controller Go file")
        if result["exists"]:
            return result
    return missing("Controller Go file")


def check_crd(project_dir: Path, group: str, version: str, kind: str) -> dict[str, Any]:
    crd_dir = project_dir / "config" / "crd" / "bases"
    candidates = list(crd_dir.glob("*.yaml")) if crd_dir.is_dir() else []
    for path in candidates:
        data = load_yaml(path)
        names = data.get("spec", {}).get("names", {})
        if data.get("kind") == "CustomResourceDefinition" and (not kind or str(names.get("kind", "")).lower() == kind):
            return {"path": rel(path), "exists": True, "valid": True, "description": "CRD manifest with expected kind"}
    return missing(f"CRD manifest for {group}/{version}/{kind}")


def check_rbac(project_dir: Path) -> dict[str, Any]:
    path = project_dir / "config" / "rbac" / "role.yaml"
    data = load_yaml(path) if path.is_file() else {}
    rules = data.get("rules") or []
    return {
        "path": rel(path),
        "exists": path.is_file(),
        "valid": bool(path.is_file() and isinstance(rules, list) and rules),
        "description": "RBAC manifest with rules",
    }


def check_sample(project_dir: Path, group: str, version: str, kind: str) -> dict[str, Any]:
    sample_dir = project_dir / "config" / "samples"
    candidates = list(sample_dir.glob("*.yaml")) if sample_dir.is_dir() else []
    expected_api = f"{group}.{load_domain(project_dir)}/{version}" if group and load_domain(project_dir) else ""
    for path in candidates:
        data = load_yaml(path)
        valid_kind = not kind or data.get("kind") == kind
        valid_api = not expected_api or data.get("apiVersion") == expected_api
        if valid_kind and valid_api:
            return {"path": rel(path), "exists": True, "valid": True, "description": "Sample Custom Resource with apiVersion/kind"}
    return missing("sample Custom Resource")


def load_domain(project_dir: Path) -> str:
    data = load_yaml(project_dir / "PROJECT")
    return str(data.get("domain") or "")


def check_test_or_make_result(record: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    validation = next((item for item in record.get("toolResults") or [] if item.get("tool") == "validation"), {})
    steps = validation.get("steps") or []
    make_test = next((item for item in steps if item.get("target") == "test"), None)
    tests_dir = project_dir / "test"
    valid = bool(make_test and make_test.get("exitCode") == 0) or tests_dir.is_dir()
    return {
        "path": rel(tests_dir) if tests_dir.exists() else "",
        "exists": bool(make_test or tests_dir.exists()),
        "valid": valid,
        "description": "make test result or test directory",
    }


def check_yaml_file(path: Path, validator: Any, description: str) -> dict[str, Any]:
    if not path.is_file():
        return missing(description, path)
    data = load_yaml(path)
    return {"path": rel(path), "exists": True, "valid": bool(data and validator(data)), "description": description}


def check_nonempty_file(path: Path, description: str) -> dict[str, Any]:
    return {"path": rel(path), "exists": path.is_file(), "valid": path.is_file() and path.stat().st_size > 0, "description": description}


def missing(description: str, path: Path | None = None) -> dict[str, Any]:
    return {"path": rel(path) if path else "", "exists": False, "valid": False, "description": description}


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, yaml.YAMLError, UnicodeDecodeError):
        return {}


def resolve_path(path: str | Path) -> Path:
    if not path:
        return Path("__missing__")
    value = Path(path)
    return value if value.is_absolute() else REPO_ROOT / value


def rel(path: Path | str) -> str:
    value = Path(path)
    try:
        return str(value.relative_to(REPO_ROOT))
    except ValueError:
        return str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check required MVP artifacts for one collected Agent log JSON.")
    parser.add_argument("--record-json", required=True)
    args = parser.parse_args()
    record = json.loads(Path(args.record_json).read_text(encoding="utf-8"))
    print(json.dumps(check_record(record), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
