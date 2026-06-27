#!/usr/bin/env python3
"""Generate a generalized Operator spec from a requirement text file.

This parser is intentionally rule-based for the MVP. Keep parsing stages
separate so an LLM/RAG parser can replace individual functions later.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


GENERATOR_VERSION = "0.1.0"
MAX_PROJECT_NAME_LENGTH = 28
DEFAULT_VERBS = ["get", "list", "watch", "create", "update", "patch", "delete"]
CUSTOM_RESOURCE_VERBS = ["get", "list", "watch", "update", "patch"]

RESOURCE_API_GROUPS = {
    "configmaps": "",
    "cronjobs": "batch",
    "daemonsets": "apps",
    "deployments": "apps",
    "jobs": "batch",
    "namespaces": "",
    "persistentvolumeclaims": "",
    "pods": "",
    "secrets": "",
    "services": "",
    "statefulsets": "apps",
}

RESOURCE_ALIASES = {
    "configmap": "configmaps",
    "configmaps": "configmaps",
    "cronjob": "cronjobs",
    "cronjobs": "cronjobs",
    "daemonset": "daemonsets",
    "daemonsets": "daemonsets",
    "deployment": "deployments",
    "deployments": "deployments",
    "job": "jobs",
    "jobs": "jobs",
    "namespace": "namespaces",
    "namespaces": "namespaces",
    "persistentvolumeclaim": "persistentvolumeclaims",
    "persistentvolumeclaims": "persistentvolumeclaims",
    "pvc": "persistentvolumeclaims",
    "pod": "pods",
    "pods": "pods",
    "secret": "secrets",
    "secrets": "secrets",
    "service": "services",
    "services": "services",
    "statefulset": "statefulsets",
    "statefulsets": "statefulsets",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate an operator-spec.yaml from a requirement file.")
    parser.add_argument("input", help="Requirement text file based on requirements/template.txt.")
    parser.add_argument("-o", "--output", help="Output path. Defaults to generated/<kind>-operator-spec.yaml.")
    parser.add_argument("--output-dir", default="generated", help="Output directory when --output is omitted.")
    args = parser.parse_args()

    source_file = Path(args.input)
    text = read_requirement(source_file)
    spec = generate_spec(text, source_file)

    output_path = Path(args.output) if args.output else default_output_path(args.output_dir, spec)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")

    print(f"Spec written: {output_path}")
    if spec["warnings"]:
        print(f"Warnings: {len(spec['warnings'])}")
    if spec["errors"]:
        print(f"Errors: {len(spec['errors'])}")
        return 2
    return 0


def read_requirement(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"requirement file not found: {path}")
    return path.read_text(encoding="utf-8")


def generate_spec(text: str, source_file: Path) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []

    api = parse_api(text, warnings)
    project = parse_project(text, api, warnings)
    spec_fields = parse_fields(text, "spec", warnings)
    status_fields = parse_fields(text, "status", warnings)
    controller = parse_controller(text, warnings)
    rbac = parse_rbac(text, api, controller, warnings)
    validation = parse_validation(text, warnings)
    sample_defaults = parse_sample_defaults(text, warnings)

    result: dict[str, Any] = {
        "metadata": parse_metadata(source_file),
        "project": project,
        "api": api,
        "specFields": spec_fields,
        "statusFields": status_fields,
        "controller": controller,
        "rbac": rbac,
        "validation": validation,
        "sampleDefaults": sample_defaults,
        "warnings": warnings,
        "errors": errors,
    }
    validate_spec(result)
    return result


def parse_sample_defaults(
    text: str,
    warnings: list[str],
) -> dict[str, Any]:
    markers = (
        "샘플 Custom Resource는 다음 값을 사용한다.",
        "Sample Custom Resource uses:",
    )
    tail = next(
        (text.split(marker, 1)[1] for marker in markers if marker in text),
        "",
    )
    if not tail:
        return {}
    lines = tail.strip().splitlines()
    try:
        spec_index = next(
            index
            for index, line in enumerate(lines)
            if line.strip() == "spec:"
        )
    except StopIteration:
        warnings.append("Sample Custom Resource section has no spec mapping.")
        return {}
    spec_lines = ["spec:"]
    for line in lines[spec_index + 1 :]:
        if line and not line[0].isspace():
            break
        spec_lines.append(line)
    try:
        parsed = yaml.safe_load("\n".join(spec_lines)) or {}
    except yaml.YAMLError:
        warnings.append("Sample Custom Resource spec YAML could not be parsed.")
        return {}
    values = parsed.get("spec") if isinstance(parsed, dict) else None
    if not isinstance(values, dict):
        warnings.append("Sample Custom Resource spec must be a mapping.")
        return {}
    return values


def parse_metadata(source_file: Path) -> dict[str, str]:
    return {
        "sourceFile": str(source_file),
        "generatedAt": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "generatorVersion": GENERATOR_VERSION,
    }


def parse_project(text: str, api: dict[str, str], warnings: list[str]) -> dict[str, str]:
    domain = api.get("domain", "")
    kind = api.get("kind", "")
    name = bounded_project_name(kind) if kind else ""
    module = f"{domain}/{name}" if domain and name else ""
    if not name:
        warnings.append("project.name could not be inferred because api.kind was not found.")
    if not module:
        warnings.append("project.module could not be inferred because domain or kind was not found.")
    if kind and name != f"{to_kebab(kind)}-operator":
        warnings.append(
            "project.name was shortened to keep generated Kubernetes "
            "resource names within the 63-character DNS limit."
        )
    return {
        "name": name,
        "domain": domain,
        "module": module,
    }


def bounded_project_name(kind: str) -> str:
    base = to_kebab(kind)
    candidate = f"{base}-operator"
    if len(candidate) <= MAX_PROJECT_NAME_LENGTH:
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:8]
    prefix_length = MAX_PROJECT_NAME_LENGTH - len("-op-") - len(digest)
    prefix = base[:prefix_length].rstrip("-")
    return f"{prefix}-op-{digest}"


def parse_api(text: str, warnings: list[str]) -> dict[str, str]:
    domain = find_value(text, r"domain\s*(?:은|는|:|=)\s*([a-z0-9.-]+\.[a-z0-9.-]+)")
    group = find_value(text, r"group\s*(?:은|는|:|=)\s*([a-z][a-z0-9-]*)")
    version = find_value(text, r"version\s*(?:은|는|:|=)\s*(v[0-9]+(?:alpha[0-9]+|beta[0-9]+)?)")
    kind = find_value(text, r"kind\s*(?:은|는|:|=)\s*([A-Z][A-Za-z0-9]*)")
    if not kind:
        kind = find_value(text, r"([A-Z][A-Za-z0-9]*)\s*라는\s+Kubernetes Custom Resource")

    for field_name, value in {
        "api.domain": domain,
        "api.group": group,
        "api.version": version,
        "api.kind": kind,
    }.items():
        if not value:
            warnings.append(f"{field_name} was not found in requirement text.")

    return {
        "domain": domain,
        "group": group,
        "version": version,
        "kind": kind,
    }


def parse_fields(text: str, section: str, warnings: list[str]) -> list[dict[str, str]]:
    block = find_section_block(text, section)
    fields: list[dict[str, str]] = []
    for line in block.splitlines():
        match = re.match(r"\s*-\s*([a-z][A-Za-z0-9]*)\s*:\s*([^\s-]+)\s*(?:-\s*(.+))?\s*$", line)
        if not match:
            continue
        name, field_type, description = match.groups()
        fields.append(
            {
                "name": name,
                "type": normalize_type(field_type),
                "description": (description or "").strip(),
            }
        )

    if not fields:
        inline_pattern = rf"{section}\s*에는\s+(.+?)을\s*포함한다"
        inline = find_value(text, inline_pattern)
        for item in re.split(r"\s*,\s*", inline):
            match = re.match(r"([a-z][A-Za-z0-9]*)\s*:\s*([^\s,]+)", item.strip())
            if not match:
                continue
            name, field_type = match.groups()
            fields.append(
                {
                    "name": name,
                    "type": normalize_type(field_type),
                    "description": "",
                }
            )

    if not fields:
        warnings.append(f"{section} fields were not found or did not match '- name:type - description'.")
    return fields


def parse_controller(text: str, warnings: list[str]) -> dict[str, Any]:
    responsibilities: list[str] = []
    managed_resources: list[str] = []
    field_mappings: list[dict[str, str]] = []
    status_rules: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip().strip(".")
        item = line[2:].strip() if line.startswith("- ") else line
        if not item:
            continue
        if "->" in item and "spec." in item:
            source, target = [part.strip() for part in item.split("->", 1)]
            field_mappings.append({"from": source, "to": target})
            managed_resources.extend(extract_k8s_resources(target))
            target_kind = mapping_target_kind(target)
            if target_kind:
                managed_resources.append(target_kind)
        elif "status." in item and ("갱신" in item or "기준" in item):
            status_rules.append(item)
            managed_resources.extend(extract_k8s_resources(item))
        elif item.startswith("Controller는"):
            responsibilities.append(item)
            managed_resources.extend(extract_k8s_resources(item))
            if "status" in item:
                status_rules.append(item)
        else:
            resources = extract_k8s_resources(item)
            if resources and ("생성" in item or "관리" in item or "조회" in item):
                responsibilities.append(item)
                managed_resources.extend(resources)

    managed_resources = unique(managed_resources)
    enabled = bool(responsibilities or managed_resources or field_mappings or status_rules)
    if not enabled:
        warnings.append("controller responsibilities were not found.")

    return {
        "enabled": enabled,
        "managedResources": managed_resources,
        "responsibilities": unique(responsibilities),
        "fieldMappings": field_mappings,
        "statusRules": unique(status_rules),
    }


def parse_rbac(text: str, api: dict[str, str], controller: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    resources: list[dict[str, Any]] = []
    group = api.get("group", "")
    domain = api.get("domain", "")
    kind = api.get("kind", "")
    if group and domain and kind:
        resources.append(
            {
                "apiGroup": f"{group}.{domain}",
                "resource": pluralize(to_kebab(kind).replace("-", "")),
                "verbs": list(CUSTOM_RESOURCE_VERBS),
            }
        )

    block = find_after_heading(text, "필요한 RBAC 권한")
    for line in block.splitlines():
        match = re.match(r"\s*-\s*([^/\s]+)/([a-z0-9-]+)", line)
        if not match:
            continue
        api_group, resource = match.groups()
        resources.append(
            {
                "apiGroup": "" if api_group == "core" else api_group,
                "resource": resource,
                "verbs": verbs_for_resource(resource),
            }
        )

    for resource in controller.get("managedResources", []):
        canonical = RESOURCE_ALIASES.get(resource.lower())
        if not canonical:
            continue
        resources.append(
            {
                "apiGroup": RESOURCE_API_GROUPS[canonical],
                "resource": canonical,
                "verbs": verbs_for_resource(canonical),
            }
        )

    resources = unique_resources(resources)
    if not resources:
        warnings.append("rbac.resources could not be inferred.")
    return {"resources": resources}


def parse_validation(text: str, warnings: list[str]) -> dict[str, list[str]]:
    block = find_after_heading(text, "검증 명령")
    commands = []
    for line in block.splitlines():
        match = re.match(r"\s*-\s*(.+)", line)
        if match:
            commands.append(match.group(1).strip())
    if not commands:
        commands = ["make generate", "make manifests", "make test"]
    return {"commands": commands}


def verbs_for_resource(resource: str) -> list[str]:
    if resource == "namespaces":
        return ["get", "list", "watch", "update", "patch"]
    return list(DEFAULT_VERBS)


def validate_spec(spec: dict[str, Any]) -> None:
    errors = spec["errors"]
    required_scalars = [
        ("project.name", spec["project"].get("name")),
        ("project.domain", spec["project"].get("domain")),
        ("project.module", spec["project"].get("module")),
        ("api.group", spec["api"].get("group")),
        ("api.version", spec["api"].get("version")),
        ("api.kind", spec["api"].get("kind")),
    ]
    for name, value in required_scalars:
        if not value:
            errors.append(f"Missing required field: {name}")

    if not spec["specFields"]:
        errors.append("Missing required field: specFields")
    if not spec["statusFields"]:
        errors.append("Missing required field: statusFields")


def default_output_path(output_dir: str, spec: dict[str, Any]) -> Path:
    kind = spec.get("api", {}).get("kind") or "unknown"
    return Path(output_dir) / f"{kind.lower()}-operator-spec.yaml"


def find_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.I | re.S)
    return match.group(1).strip(" .,`'\"") if match else ""


def find_section_block(text: str, section: str) -> str:
    match = re.search(rf"{section}\s*에는\s*다음\s*필드를\s*포함한다\.\s*(.*?)(?:\n\s*\n|$)", text, re.S | re.I)
    return match.group(1) if match else ""


def find_after_heading(text: str, heading: str) -> str:
    idx = text.find(heading)
    if idx < 0:
        return ""
    tail = text[idx:]
    parts = re.split(r"\n\s*\n", tail, maxsplit=1)
    return parts[0] if parts else tail


def extract_k8s_resources(line: str) -> list[str]:
    resources: list[str] = []
    for alias, canonical in RESOURCE_ALIASES.items():
        pattern = rf"(?<![A-Za-z0-9]){re.escape(alias)}(?:과|와|를|을|는|은|의|에|,|\s|$)"
        if re.search(pattern, line, re.I):
            resources.append(resource_kind(canonical))
    return unique(resources)


def mapping_target_kind(target: str) -> str:
    match = re.match(r"([A-Z][A-Za-z0-9]*)\.", target)
    return match.group(1) if match else ""


def resource_kind(resource: str) -> str:
    names = {
        "configmaps": "ConfigMap",
        "cronjobs": "CronJob",
        "daemonsets": "DaemonSet",
        "deployments": "Deployment",
        "jobs": "Job",
        "namespaces": "Namespace",
        "persistentvolumeclaims": "PVC",
        "pods": "Pod",
        "secrets": "Secret",
        "services": "Service",
        "statefulsets": "StatefulSet",
    }
    return names.get(resource, resource)


def normalize_type(value: str) -> str:
    aliases = {
        "int": "int32",
        "integer": "int32",
        "boolean": "bool",
    }
    return aliases.get(value.lower(), value)


def to_kebab(value: str) -> str:
    return re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value).lower()


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
        key = (item["apiGroup"], item["resource"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
