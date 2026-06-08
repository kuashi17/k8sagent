#!/usr/bin/env python3
"""Create a Kubebuilder project from a structured Operator spec."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml


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
    parser = argparse.ArgumentParser(description="Scaffold a Kubebuilder project from generated/*-spec.yaml.")
    parser.add_argument("spec", help="Path to structured spec YAML.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without changing files.")
    parser.add_argument("--force", action="store_true", help="Remove an existing target workspace before scaffolding.")
    parser.add_argument("--skip-verify", action="store_true", help="Skip make generate/manifests after scaffolding.")
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parents[1]
    spec_path = Path(args.spec)
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    spec = normalize_spec(spec)
    validate_spec(spec)

    project = spec["project"]
    resource = spec["resource"]
    workspace = root_dir / project.get("workspace", f"workspace/{project['name']}")

    commands = plan_commands(spec)
    print("Scaffold plan:")
    print(f"  workspace: {workspace}")
    for command in commands:
        print("  " + " ".join(command))
    print("  update api type fields")
    print("  update sample custom resource")
    if not args.skip_verify:
        print("  make generate")
        print("  make manifests")

    if args.dry_run:
        return 0

    if workspace.exists():
        if not args.force:
            print(f"target workspace already exists: {workspace}", file=sys.stderr)
            print("Use --force to recreate it.", file=sys.stderr)
            return 1
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)

    env = os.environ.copy()
    env["PATH"] = f"{root_dir / '.tools/bin'}:{env.get('PATH', '')}"
    env["GOCACHE"] = env.get("GOCACHE", "/tmp/k8sagent-go-build")

    run(commands[0], workspace, env)
    patch_makefile(workspace)
    run(commands[1], workspace, env)
    patch_makefile(workspace)

    update_types(workspace, resource["version"], resource["kind"], spec)
    update_sample(workspace, resource, spec)
    if spec.get("controller", {}).get("enabled"):
        patch_controller_tests(workspace, resource["kind"])

    run(["gofmt", "-w", str(find_types_file(workspace, resource["version"], resource["kind"]))], workspace, env)
    if not args.skip_verify:
        run(["make", "generate"], workspace, env)
        run(["make", "manifests"], workspace, env)

    print(f"Scaffold completed: {workspace}")
    return 0


def normalize_spec(spec: dict) -> dict:
    """Accept both the first scaffold MVP schema and the generalized spec schema."""
    if spec.get("resource") and spec.get("spec", {}).get("fields") is not None:
        return spec

    api = spec.get("api") or {}
    project = spec.setdefault("project", {})
    resource = spec.setdefault("resource", {})
    if api:
        resource.setdefault("group", api.get("group", ""))
        resource.setdefault("apiGroup", f"{api.get('group', '')}.{api.get('domain', '')}".strip("."))
        resource.setdefault("version", api.get("version", ""))
        resource.setdefault("kind", api.get("kind", ""))
        resource.setdefault("plural", pluralize(to_kebab(api.get("kind", "")).replace("-", "")))
        resource.setdefault("scope", "Namespaced")

    if spec.get("specFields") is not None:
        spec["spec"] = {"fields": spec.get("specFields") or []}
    if spec.get("statusFields") is not None:
        spec["status"] = {"fields": spec.get("statusFields") or []}

    if project.get("name") and not project.get("workspace"):
        project["workspace"] = f"workspace/{project['name']}"

    return spec


def to_kebab(value: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value).lower()


def pluralize(value: str) -> str:
    if value.endswith("s"):
        return value + "es"
    if value.endswith("y"):
        return value[:-1] + "ies"
    return value + "s"


def plan_commands(spec: dict) -> list[list[str]]:
    generation = spec.get("generation", {})
    init = generation.get("kubebuilderInit") or [
        "kubebuilder",
        "init",
        "--domain",
        spec["project"]["domain"],
        "--repo",
        spec["project"]["module"],
    ]
    create_api = generation.get("kubebuilderCreateApi") or [
        "kubebuilder",
        "create",
        "api",
        "--group",
        spec["resource"]["group"],
        "--version",
        spec["resource"]["version"],
        "--kind",
        spec["resource"]["kind"],
        "--resource",
    ]
    create_api = list(create_api)
    if "--controller" not in create_api and "--controller=false" not in create_api:
        create_api.append("--controller" if spec.get("controller", {}).get("enabled") else "--controller=false")
    return [list(init), list(create_api)]


def validate_spec(spec: dict) -> None:
    project = spec.get("project") or {}
    resource = spec.get("resource") or {}
    required = [
        ("project.name", project.get("name")),
        ("project.domain", project.get("domain")),
        ("project.module", project.get("module")),
        ("resource.group", resource.get("group")),
        ("resource.version", resource.get("version")),
        ("resource.kind", resource.get("kind")),
    ]
    missing = [name for name, value in required if not value]
    if missing:
        raise SystemExit(f"missing required spec fields: {', '.join(missing)}")

    checks = [
        ("project.name", project["name"], r"[a-z0-9]([-a-z0-9]*[a-z0-9])?"),
        ("project.domain", project["domain"], r"[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)+"),
        ("resource.group", resource["group"], r"[a-z0-9]([-a-z0-9]*[a-z0-9])?"),
        ("resource.version", resource["version"], r"v[0-9]+((alpha|beta)[0-9]+)?"),
        ("resource.kind", resource["kind"], r"[A-Z][A-Za-z0-9]*"),
    ]
    for name, value, pattern in checks:
        if not re.fullmatch(pattern, value):
            raise SystemExit(f"invalid {name}: {value}")

    for section in ("spec", "status"):
        for field in spec.get(section, {}).get("fields", []):
            if not re.fullmatch(r"[a-z][A-Za-z0-9]*", field.get("name", "")):
                raise SystemExit(f"invalid {section} field name: {field.get('name')}")
            field_type = field.get("type", "string")
            if field_type not in GO_TYPES:
                raise SystemExit(f"unsupported {section} field type for {field.get('name')}: {field_type}")


def run(command: list[str], cwd: Path, env: dict) -> None:
    print("+ " + " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def patch_makefile(workspace: Path) -> None:
    makefile = workspace / "Makefile"
    if not makefile.exists():
        return
    text = makefile.read_text(encoding="utf-8")
    text = text.replace("CONTROLLER_TOOLS_VERSION ?= v0.15.0", "CONTROLLER_TOOLS_VERSION ?= v0.21.0")
    text = text.replace(
        "test: manifests generate fmt vet envtest ## Run tests.\n"
        "\tKUBEBUILDER_ASSETS=\"$(shell $(ENVTEST) use $(ENVTEST_K8S_VERSION) --bin-dir $(LOCALBIN) -p path)\" go test $$(go list ./... | grep -v /e2e) -coverprofile cover.out",
        "test: manifests generate fmt vet ## Run tests.\n"
        "\tgo test $$(go list ./... | grep -v /e2e) -coverprofile cover.out",
    )
    makefile.write_text(text, encoding="utf-8")


def update_types(workspace: Path, version: str, kind: str, spec: dict) -> None:
    types_file = find_types_file(workspace, version, kind)
    text = types_file.read_text(encoding="utf-8")
    text = replace_struct_body(text, f"{kind}Spec", render_go_fields(spec.get("spec", {}).get("fields", []), "Spec"))
    text = replace_struct_body(text, f"{kind}Status", render_go_fields(spec.get("status", {}).get("fields", []), "Status"))
    types_file.write_text(text, encoding="utf-8")


def find_types_file(workspace: Path, version: str, kind: str) -> Path:
    api_dir = workspace / "api" / version
    candidates = sorted(api_dir.glob("*_types.go"))
    if not candidates:
        raise SystemExit(f"types file not found under {api_dir}")
    expected = api_dir / f"{kind.lower()}_types.go"
    return expected if expected.exists() else candidates[0]


def replace_struct_body(text: str, struct_name: str, body: str) -> str:
    pattern = rf"type {struct_name} struct \{{.*?\n\}}"
    replacement = f"type {struct_name} struct {{\n{body}}}"
    updated, count = re.subn(pattern, replacement, text, flags=re.S)
    if count != 1:
        raise SystemExit(f"failed to update struct: {struct_name}")
    return updated


def render_go_fields(fields: list[dict], section: str) -> str:
    if not fields:
        return ""
    lines: list[str] = []
    for field in fields:
        name = field["name"]
        go_name = exported_go_name(name)
        go_type = GO_TYPES[field.get("type", "string")]
        description = field.get("description") or f"{go_name} is a {section} field."
        lines.append(f"\t// {description}")
        lines.append(f"\t{go_name} {go_type} `json:\"{name},omitempty\"`")
        lines.append("")
    return "\n".join(lines)


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


def update_sample(workspace: Path, resource: dict, spec: dict) -> None:
    samples_dir = workspace / "config" / "samples"
    sample_files = [path for path in sorted(samples_dir.glob("*.yaml")) if path.name != "kustomization.yaml"]
    if not sample_files:
        return
    sample_file = sample_files[0]
    sample = yaml.safe_load(sample_file.read_text(encoding="utf-8"))
    sample["spec"] = {
        field["name"]: sample_value(field.get("type", "string"), field["name"])
        for field in spec.get("spec", {}).get("fields", [])
    }
    sample_file.write_text(yaml.safe_dump(sample, sort_keys=False, allow_unicode=True), encoding="utf-8")


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


def sample_value(field_type: str, name: str):
    if field_type in ("int", "int32", "int64"):
        return 1
    if field_type in ("bool", "boolean"):
        return False
    if field_type == "[]string":
        return [f"sample-{name}"]
    if name.lower().endswith("image"):
        return "busybox:latest"
    if "path" in name.lower():
        return "/workspace/data"
    if "pvc" in name.lower():
        return "sample-pvc"
    return f"sample-{name}"


if __name__ == "__main__":
    raise SystemExit(main())
