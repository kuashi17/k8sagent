#!/usr/bin/env python3
"""Patch Kubebuilder artifacts from a generated Operator spec."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.tools.controller_renderer import render_controller
from agent.tools.controller_ir_builder import build_controller_ir


GO_TYPES = {
    "string": "string",
    "int": "int32",
    "int32": "int32",
    "int64": "int64",
    "bool": "bool",
    "boolean": "bool",
    "[]string": "[]string",
    "[]int32": "[]int32",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch Kubebuilder artifacts from operator-spec.yaml.")
    parser.add_argument("--input", required=True, help="Path to generated operator spec YAML.")
    parser.add_argument("--project", required=True, help="Path to generated Kubebuilder project.")
    parser.add_argument("--profile", help="Path to an Operator profile YAML. Profile sample defaults override generic sample values.")
    parser.add_argument("--dry-run", action="store_true", help="Print diffs without changing files. This is the default.")
    parser.add_argument("--execute", action="store_true", help="Apply patches. Validation commands are not run automatically.")
    args = parser.parse_args()

    if args.dry_run and args.execute:
        print("Use either --dry-run or --execute, not both.", file=sys.stderr)
        return 2

    spec_path = Path(args.input)
    project_dir = Path(args.project)
    spec = load_spec(spec_path)
    profile = load_profile(Path(args.profile)) if args.profile else {}
    errors = spec.get("errors") or []
    if errors:
        print("Cannot patch artifacts because operator spec has errors:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    model = normalize_spec(spec, profile, args.profile)
    missing = required_missing(model)
    if missing:
        print("Cannot patch artifacts because required fields are missing:", file=sys.stderr)
        for field in missing:
            print(f"- {field}", file=sys.stderr)
        return 2

    changes = build_changes(project_dir, model)
    diff_text = render_combined_diff(changes)

    print_patch_context(model)
    if not diff_text.strip():
        print("No artifact changes are required.")
    else:
        print(diff_text)

    if not args.execute:
        print("Dry-run mode: no files were modified and no validation commands were executed.")
        return 0

    return execute_patch(spec_path, project_dir, model, changes, diff_text)


def load_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"operator spec not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"operator spec must be a YAML mapping: {path}")
    return data


def load_profile(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"profile YAML not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"profile YAML must be a mapping: {path}")
    data["_profilePath"] = str(path)
    return data


def normalize_spec(spec: dict[str, Any], profile: dict[str, Any], profile_path: str | None) -> dict[str, Any]:
    api = spec.get("api") or spec.get("resource") or {}
    project = spec.get("project") or {}
    spec_fields = spec.get("specFields") or spec.get("spec", {}).get("fields") or []
    status_fields = spec.get("statusFields") or spec.get("status", {}).get("fields") or []
    patcher_profile = profile.get("artifactPatcher") or {}
    rbac_resources = list(spec.get("rbac", {}).get("resources") or [])
    rbac_resources.extend(
        item
        for item in patcher_profile.get("rbacResources") or []
        if isinstance(item, dict)
    )
    profile_sample_defaults = profile.get("sampleDefaults", {}).get("spec") or {}

    kind = api.get("kind", "")
    version = api.get("version", "")
    group = api.get("group", "")
    domain = api.get("domain") or project.get("domain") or infer_domain(api.get("apiGroup", ""), group)
    api_group = f"{group}.{domain}" if group and domain else api.get("apiGroup", "")

    plural = api.get("plural") or pluralize(kind.lower())
    if status_fields and api_group and plural:
        status_resource = f"{plural}/status"
        if not any(
            item.get("apiGroup") == api_group
            and item.get("resource") == status_resource
            for item in rbac_resources
        ):
            rbac_resources.append(
                {
                    "apiGroup": api_group,
                    "resource": status_resource,
                    "verbs": ["get", "update", "patch"],
                }
            )
    return {
        "project": project,
        "api": {
            "kind": kind,
            "plural": plural,
            "version": version,
            "group": group,
            "domain": domain,
            "apiGroup": api_group,
        },
        "specFields": spec_fields,
        "statusFields": status_fields,
        "controller": spec.get("controller") or {},
        "rbacResources": normalize_rbac(api_group, plural, rbac_resources, spec_fields),
        "profile": {
            "path": profile_path or "",
            "name": profile.get("profileName", ""),
            "sampleDefaults": profile_sample_defaults,
        },
        "controllerPatches": [
            item
            for item in patcher_profile.get("controllerPatches") or []
            if isinstance(item, dict)
        ],
        "rbacSource": "spec.rbac.resources" if rbac_resources else "fallback",
        "validationCommands": spec.get("validation", {}).get("commands") or ["make generate", "make manifests", "make test"],
    }


def required_missing(model: dict[str, Any]) -> list[str]:
    checks = {
        "api.kind": model["api"].get("kind"),
        "api.version": model["api"].get("version"),
        "api.group": model["api"].get("group"),
        "api.domain": model["api"].get("domain"),
        "specFields": model.get("specFields"),
        "statusFields": model.get("statusFields"),
    }
    return [name for name, value in checks.items() if not value]


def normalize_rbac(api_group: str, plural: str, resources: list[dict[str, Any]], spec_fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if resources:
        result = [
            {
                "apiGroup": item.get("apiGroup", ""),
                "resource": item.get("resource", ""),
                "verbs": item.get("verbs") or ["get", "list", "watch"],
            }
            for item in resources
            if item.get("resource")
        ]
        ensure_resource(
            result,
            api_group,
            plural,
            ["get", "list", "watch", "update", "patch"],
        )
        ensure_resource(
            result,
            api_group,
            f"{plural}/status",
            ["get", "update", "patch"],
        )
        return unique_resources(result)

    result: list[dict[str, Any]] = [
        {"apiGroup": api_group, "resource": plural, "verbs": ["get", "list", "watch", "create", "update", "patch", "delete"]},
        {"apiGroup": api_group, "resource": f"{plural}/status", "verbs": ["get", "update", "patch"]},
    ]
    for item in resources:
        resource = item.get("resource", "")
        if resource == plural:
            continue
        result.append(
            {
                "apiGroup": item.get("apiGroup", ""),
                "resource": resource,
                "verbs": item.get("verbs") or ["get", "list", "watch"],
            }
        )

    ensure_resource(result, "batch", "jobs", ["get", "list", "watch", "create", "update", "patch", "delete"])
    ensure_resource(result, "", "pods", ["get", "list", "watch", "create", "update", "patch", "delete"])
    if any("pvc" in field.get("name", "").lower() for field in spec_fields):
        ensure_resource(result, "", "persistentvolumeclaims", ["get", "list", "watch"])
    return unique_resources(result)


def ensure_resource(resources: list[dict[str, Any]], api_group: str, resource: str, verbs: list[str]) -> None:
    for item in resources:
        if item.get("apiGroup", "") == api_group and item.get("resource") == resource:
            item["verbs"] = unique([*(item.get("verbs") or []), *verbs])
            return
    resources.append({"apiGroup": api_group, "resource": resource, "verbs": verbs})


def build_changes(project_dir: Path, model: dict[str, Any]) -> list[dict[str, Any]]:
    api = model["api"]
    kind = api["kind"]
    version = api["version"]
    lower_kind = kind.lower()

    types_file = project_dir / "api" / version / f"{lower_kind}_types.go"
    sample_file = project_dir / "config" / "samples" / f"{api['group']}_v1alpha1_{lower_kind}.yaml"
    controller_file = project_dir / "internal" / "controller" / f"{lower_kind}_controller.go"

    require_file(types_file)
    require_file(sample_file)
    require_file(controller_file)

    changes = [
        file_change(types_file, patch_types(types_file.read_text(encoding="utf-8"), model)),
        file_change(sample_file, patch_sample(sample_file.read_text(encoding="utf-8"), model)),
        file_change(controller_file, patch_controller(controller_file.read_text(encoding="utf-8"), model)),
    ]
    return changes


def print_patch_context(model: dict[str, Any]) -> None:
    profile = model.get("profile") or {}
    profile_label = profile.get("path") or "not provided"
    profile_name = profile.get("name") or "none"
    sample_defaults = profile.get("sampleDefaults") or {}
    print("Patch context")
    print(f"- profile: {profile_name} ({profile_label})")
    print(f"- spec fields: {', '.join(field['name'] for field in model['specFields'])}")
    print(f"- status fields: {', '.join(field['name'] for field in model['statusFields'])}")
    print(f"- RBAC source: {model.get('rbacSource')}")
    print(f"- RBAC resources: {', '.join(format_rbac_resource(item) for item in model['rbacResources'])}")
    if sample_defaults:
        print(f"- profile sample defaults: {', '.join(sample_defaults.keys())}")
    else:
        print("- profile sample defaults: none")
    if not profile.get("path") and (
        model.get("controller") or {}
    ).get("managedResources"):
        ir = build_controller_ir(model)
        print(
            "- controller IR: "
            + ", ".join(
                (
                    f"{item.kind}[{item.strategy.value},"
                    f"{item.scope.value},{item.ownership.value}]"
                )
                for item in ir.managed_resources
            )
        )
    print()


def format_rbac_resource(item: dict[str, Any]) -> str:
    group = item.get("apiGroup", "") or "core"
    return f"{group}/{item.get('resource', '')}"


def require_file(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"required project file not found: {path}")


def file_change(path: Path, new_text: str) -> dict[str, Any]:
    old_text = path.read_text(encoding="utf-8")
    return {"path": path, "old": old_text, "new": new_text}


def patch_types(text: str, model: dict[str, Any]) -> str:
    kind = model["api"]["kind"]
    text = replace_struct_body(text, f"{kind}Spec", render_go_fields(model["specFields"], "Spec"))
    text = replace_struct_body(text, f"{kind}Status", render_go_fields(model["statusFields"], "Status"))
    return text


def replace_struct_body(text: str, struct_name: str, body: str) -> str:
    pattern = rf"type {struct_name} struct \{{.*?\n\}}"
    replacement = f"type {struct_name} struct {{\n{body}}}"
    updated, count = re.subn(pattern, replacement, text, flags=re.S)
    if count != 1:
        raise SystemExit(f"failed to update struct: {struct_name}")
    return updated


def render_go_fields(fields: list[dict[str, Any]], section: str) -> str:
    lines: list[str] = []
    for field in fields:
        name = field["name"]
        go_type = GO_TYPES.get(field.get("type", "string"), field.get("type", "string"))
        go_name = exported_go_name(name)
        description = field.get("description") or f"{go_name} is a {section} field."
        lines.append(f"\t// {description}")
        lines.extend(validation_markers(go_type))
        lines.append(f"\t{go_name} {go_type} `json:\"{name},omitempty\"`")
        lines.append("")
    return "\n".join(lines)


def validation_markers(go_type: str) -> list[str]:
    markers = ["\t// +kubebuilder:validation:Optional"]
    if go_type == "string":
        markers.append("\t// +kubebuilder:validation:MinLength=1")
    elif go_type in ("int32", "int64", "int"):
        markers.append("\t// +kubebuilder:validation:Minimum=0")
    return markers


def patch_sample(text: str, model: dict[str, Any]) -> str:
    sample = yaml.safe_load(text)
    profile_defaults = model.get("profile", {}).get("sampleDefaults") or {}
    sample["spec"] = {
        field["name"]: profile_defaults.get(field["name"], sample_value(field.get("type", "string"), field["name"]))
        for field in model["specFields"]
    }
    return yaml.safe_dump(sample, sort_keys=False, allow_unicode=True)


def patch_controller(text: str, model: dict[str, Any]) -> str:
    if (
        not (model.get("profile") or {}).get("path")
        and model.get("project")
        and (model.get("controller") or {}).get("managedResources")
    ):
        rendered = render_controller(model)
        validate_controller_markers(rendered, model)
        validate_controller_behavior(rendered, model)
        return rendered
    kind = model["api"]["kind"]
    marker_block = "\n".join(render_rbac_marker(item) for item in model["rbacResources"])
    marker_block += "\n"
    pattern = (
        rf"(type {kind}Reconciler struct \{{.*?\n\}}\n\n)"
        rf"(?:// \+kubebuilder:rbac:[^\n]*\n)+"
    )
    replacement = rf"\1{marker_block}"
    updated, count = re.subn(pattern, replacement, text, flags=re.S)
    if count != 1:
        raise SystemExit(f"failed to update RBAC markers for {kind} controller")
    updated = apply_controller_patches(
        updated,
        model.get("controllerPatches") or [],
    )
    validate_controller_markers(updated, model)
    validate_controller_behavior(updated, model)
    return updated


def apply_controller_patches(
    text: str,
    patches: list[dict[str, Any]],
) -> str:
    updated = text
    for index, patch in enumerate(patches):
        before = str(patch.get("before") or "")
        after = str(patch.get("after") or "")
        if not before or not after:
            raise SystemExit(
                f"profile controllerPatches[{index}] requires before and after"
            )
        if after in updated:
            continue
        count = updated.count(before)
        if count != 1:
            raise SystemExit(
                f"profile controllerPatches[{index}] expected one match, got {count}"
            )
        updated = updated.replace(before, after, 1)
    return updated


def validate_controller_markers(
    text: str,
    model: dict[str, Any],
) -> None:
    missing = [
        render_rbac_marker(item)
        for item in model["rbacResources"]
        if render_rbac_marker(item) not in text
    ]
    if missing:
        raise SystemExit(
            "controller RBAC marker validation failed: " + ", ".join(missing)
        )


def validate_controller_behavior(
    text: str,
    model: dict[str, Any],
) -> None:
    managed = (model.get("controller") or {}).get(
        "managedResources",
        [],
    )
    if not managed:
        return
    if "TODO(user): your logic here" in text:
        raise SystemExit(
            "controller behavior validation failed: scaffold TODO remains "
            "for managed resources "
            + ", ".join(str(item) for item in managed)
        )


def render_rbac_marker(item: dict[str, Any]) -> str:
    group = item.get("apiGroup", "")
    group_value = '""' if group == "" else group
    resources = item.get("resource", "")
    verbs = ";".join(item.get("verbs") or ["get", "list", "watch"])
    return f"// +kubebuilder:rbac:groups={group_value},resources={resources},verbs={verbs}"


def render_combined_diff(changes: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for change in changes:
        if change["old"] == change["new"]:
            continue
        chunks.extend(
            difflib.unified_diff(
                change["old"].splitlines(keepends=True),
                change["new"].splitlines(keepends=True),
                fromfile=f"{change['path']} (before)",
                tofile=f"{change['path']} (after)",
            )
        )
    return "".join(chunks)


def execute_patch(spec_path: Path, project_dir: Path, model: dict[str, Any], changes: list[dict[str, Any]], diff_text: str) -> int:
    log_dir = Path("logs") / "patch" / datetime.now().strftime("%Y%m%d-%H%M%S")
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "diff.patch").write_text(diff_text, encoding="utf-8")
    if not (model.get("profile") or {}).get("path") and (
        model.get("controller") or {}
    ).get("managedResources"):
        (log_dir / "controller-ir.json").write_text(
            json.dumps(
                build_controller_ir(model).to_dict(),
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    summary: dict[str, Any] = {
        "input": str(spec_path),
        "projectDir": str(project_dir),
        "profile": model.get("profile", {}),
        "execute": True,
        "logDir": str(log_dir),
        "changedFiles": [str(change["path"]) for change in changes if change["old"] != change["new"]],
        "steps": [],
        "failedStep": None,
    }

    for change in changes:
        if change["old"] != change["new"]:
            change["path"].write_text(change["new"], encoding="utf-8")

    commands = [
        {"name": "gofmt", "command": ["gofmt", "-w", str(project_dir / "api" / model["api"]["version"] / f"{model['api']['kind'].lower()}_types.go"), str(project_dir / "internal" / "controller" / f"{model['api']['kind'].lower()}_controller.go")], "cwd": "."},
    ]

    env = os.environ.copy()
    env["PATH"] = f"{Path.cwd() / '.tools/bin'}:{env.get('PATH', '')}"
    env["GOCACHE"] = env.get("GOCACHE", "/tmp/k8sagent-go-build")

    for index, step in enumerate(commands, start=1):
        result = run_step(index, step, log_dir, env)
        summary["steps"].append(result)
        write_summary(log_dir, summary)
        if result["status"] != "succeeded":
            summary["failedStep"] = result["name"]
            write_summary(log_dir, summary)
            print(f"Artifact patch failed at step: {result['name']} (exit code {result['exitCode']})", file=sys.stderr)
            print(f"Logs: {log_dir}", file=sys.stderr)
            return result["exitCode"] or 1

    write_summary(log_dir, summary)
    print(f"Artifact patch completed: {project_dir}")
    print(f"Logs: {log_dir}")
    return 0


def run_step(index: int, step: dict[str, Any], log_dir: Path, env: dict[str, str]) -> dict[str, Any]:
    stdout_log = log_dir / f"{index:02d}-{step['name']}.stdout.log"
    stderr_log = log_dir / f"{index:02d}-{step['name']}.stderr.log"
    print(f"+ ({step['cwd']}) {' '.join(step['command'])}")
    completed = subprocess.run(step["command"], cwd=Path(step["cwd"]), env=env, text=True, capture_output=True)
    stdout_log.write_text(completed.stdout, encoding="utf-8")
    stderr_log.write_text(completed.stderr, encoding="utf-8")
    return {
        "name": step["name"],
        "command": step["command"],
        "cwd": step["cwd"],
        "exitCode": completed.returncode,
        "status": "succeeded" if completed.returncode == 0 else "failed",
        "stdoutLog": str(stdout_log),
        "stderrLog": str(stderr_log),
    }


def write_summary(log_dir: Path, summary: dict[str, Any]) -> None:
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def exported_go_name(name: str) -> str:
    value = name[:1].upper() + name[1:]
    initialisms = {
        "Gpu": "GPU",
        "Pvc": "PVC",
        "Url": "URL",
        "Uri": "URI",
        "Id": "ID",
        "Ip": "IP",
    }
    for old, new in initialisms.items():
        if value.startswith(old):
            value = new + value[len(old) :]
    return value


def sample_value(field_type: str, name: str) -> Any:
    semantic = semantic_sample_value(name)
    if semantic is not None:
        return semantic
    normalized = field_type.lower()
    if normalized in ("int", "int32", "int64"):
        return 1
    if normalized in ("bool", "boolean"):
        return True
    if normalized.startswith("[]"):
        return [f"sample-{name}"]
    if normalized.startswith("map[") or normalized in ("object", "map"):
        return {"sample": "value"}
    return f"sample-{kebab_case(name)}"


def semantic_sample_value(name: str) -> Any:
    values = {
        "accessModes": ["ReadWriteOnce"],
        "command": ["echo", "hello"],
        "cpuLimit": "100m",
        "env": {"MODE": "test"},
        "healthPath": "/healthz",
        "healthPort": 8080,
        "image": "nginx:latest",
        "memoryLimit": "128Mi",
        "mountPath": "/workspace",
        "namespaceName": "default",
        "pvcName": "sample-workload-pvc",
        "readinessPath": "/readyz",
        "readinessPort": 8080,
        "resourceLimits": {"cpu": "100m", "memory": "128Mi"},
        "schedule": "*/5 * * * *",
        "storageClassName": "standard",
        "storageSize": "1Gi",
    }
    return values.get(name)


def kebab_case(value: str) -> str:
    separated = re.sub(r"(?<!^)(?=[A-Z])", "-", value)
    return re.sub(r"[^a-z0-9-]+", "-", separated.lower()).strip("-")


def infer_domain(api_group: str, group: str) -> str:
    prefix = f"{group}."
    if api_group.startswith(prefix):
        return api_group[len(prefix) :]
    return ""


def pluralize(value: str) -> str:
    if value.endswith("s"):
        return value + "es"
    if value.endswith("y"):
        return value[:-1] + "ies"
    return value + "s"


def unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def unique_resources(resources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in resources:
        key = (item.get("apiGroup", ""), item.get("resource", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
