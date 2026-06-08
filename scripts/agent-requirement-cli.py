#!/usr/bin/env python3
"""Parse an Operator requirement text into a structured MVP spec."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


TYPE_HINTS = {
    "size": "int32",
    "replicas": "int32",
    "readyReplicas": "int32",
    "ready_replicas": "int32",
    "port": "int32",
    "ports": "[]int32",
    "enabled": "bool",
    "succeeded": "bool",
}

KNOWN_K8S_RESOURCES = {
    "configmap": "ConfigMap",
    "cronjob": "CronJob",
    "daemonset": "DaemonSet",
    "deployment": "Deployment",
    "job": "Job",
    "pod": "Pod",
    "pvc": "PVC",
    "persistentvolumeclaim": "PVC",
    "secret": "Secret",
    "service": "Service",
    "statefulset": "StatefulSet",
}


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        return run_interactive(sys.argv[2:])

    parser = argparse.ArgumentParser(
        description="Convert a natural-language Operator request into a structured YAML spec."
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to a requirement text file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output YAML path. Defaults to generated/<project-name>-spec.yaml.",
    )
    parser.add_argument(
        "--print-commands",
        action="store_true",
        help="Print the Kubebuilder commands derived from the parsed spec.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"input file not found: {input_path}", file=sys.stderr)
        return 1

    text = input_path.read_text(encoding="utf-8")
    spec = parse_requirement(text)

    root_dir = Path(__file__).resolve().parents[1]
    output_path = Path(args.output) if args.output else root_dir / "generated" / f"{spec['project']['name']}-spec.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_yaml(spec), encoding="utf-8")

    print(f"Structured spec written: {output_path}")
    if args.print_commands:
        print()
        print("Kubebuilder command plan:")
        print("  " + " ".join(spec["generation"]["kubebuilderInit"]))
        print("  " + " ".join(spec["generation"]["kubebuilderCreateApi"]))

    return 0


def run_interactive(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-requirement-cli.py interactive",
        description="Interview a beginner and create a structured Operator spec.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Output YAML path. Defaults to generated/<project-name>-spec.yaml.",
    )
    parser.add_argument(
        "--print-commands",
        action="store_true",
        help="Print the Kubebuilder commands derived from the interview.",
    )
    args = parser.parse_args(argv)

    print("Operator requirement interview")
    print("Answer in your own words. Press Enter to accept a suggested default.")
    print()

    purpose = ask("무엇을 자동화하거나 관리하고 싶나요?", "Redis cache, backup policy, training job")
    suggested_kind = suggest_kind(purpose)
    kind = ask_validated("Custom Resource 이름은 무엇으로 할까요?", suggested_kind, is_valid_kind, "예: RedisCache, TrainingJob, BackupPolicy")
    domain = ask_validated("API domain은 무엇으로 할까요?", "sample.io", is_valid_domain, "예: sample.io, ai.sample.io")
    group = ask_validated("API group은 무엇으로 할까요?", lower_camel_to_kebab(kind).split("-")[0], is_valid_dns_label, "영문 소문자, 숫자, '-'만 사용할 수 있습니다. 예: cache, ml, backup")
    version = ask_validated("API version은 무엇으로 할까요?", "v1alpha1", is_valid_version, "예: v1alpha1, v1beta1, v1")

    print()
    print("사용자가 Custom Resource를 만들 때 입력해야 하는 값을 적어주세요.")
    print("예: image:string, size:int32, storageSize:string")
    spec_fields = ask_fields("spec 입력값", suggest_spec_fields(purpose))

    print()
    print("사용자가 kubectl로 보고 싶은 상태 정보를 적어주세요.")
    print("예: phase:string, readyReplicas:int32, message:string")
    status_fields = ask_fields("status 상태값", suggest_status_fields(purpose))

    print()
    managed_resources = ask(
        "Operator가 대신 생성하거나 관리할 Kubernetes 리소스는 무엇인가요?",
        suggest_managed_resources(purpose),
    )
    managed_resources = normalize_resource_list(managed_resources)
    if not managed_resources:
        print("유효한 Kubernetes 리소스를 찾지 못했습니다. 예: Deployment, StatefulSet, Service, Job, Pod, PVC")
        managed_resources = ask("다시 입력해주세요", suggest_managed_resources(purpose))
        managed_resources = normalize_resource_list(managed_resources)

    print()
    print("입력값이 생성 리소스에 어떻게 반영되는지 적어주세요.")
    print("모르면 Enter를 누르고 나중에 보완해도 됩니다.")
    print("예: image -> container image, size -> replicas, storageSize -> PVC storage")
    mappings = ask_multiline("spec-to-resource 매핑")

    print()
    print("상태값을 어떤 기준으로 갱신해야 하는지 적어주세요.")
    print("예: StatefulSet readyReplicas를 status.readyReplicas에 반영")
    status_rules = ask_multiline("status 갱신 기준")

    responsibilities = []
    if managed_resources:
        responsibilities.append(f"Create or manage Kubernetes resources: {managed_resources}")
    responsibilities.extend(mappings)
    responsibilities.extend(status_rules)

    spec = build_spec(
        kind=kind,
        domain=domain,
        group=group,
        version=version,
        spec_fields=spec_fields,
        status_fields=status_fields,
        controller_enabled=bool(responsibilities),
        responsibilities=responsibilities,
    )

    root_dir = Path(__file__).resolve().parents[1]
    output_path = Path(args.output) if args.output else root_dir / "generated" / f"{spec['project']['name']}-spec.yaml"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_yaml(spec), encoding="utf-8")

    print()
    print(f"Structured spec written: {output_path}")
    if args.print_commands:
        print()
        print("Kubebuilder command plan:")
        print("  " + " ".join(spec["generation"]["kubebuilderInit"]))
        print("  " + " ".join(spec["generation"]["kubebuilderCreateApi"]))
    return 0


def parse_requirement(text: str) -> dict:
    kind = find_value(text, r"\bkind\s*(?:은|는|:|=)\s*([A-Z][A-Za-z0-9]*)")
    if not kind:
        kind = find_value(text, r"([A-Z][A-Za-z0-9]*)\s*(?:라는|라는\s+Kubernetes|Custom Resource|Operator)")
    if not kind:
        raise SystemExit("failed to parse kind from requirement")

    domain = find_value(text, r"\bdomain\s*(?:은|는|:|=)\s*([a-z0-9.-]+\.[a-z0-9.-]+)") or "example.com"
    group = find_value(text, r"\bgroup\s*(?:은|는|:|=)\s*([a-z][a-z0-9-]*)") or lower_camel_to_kebab(kind)
    version = find_value(text, r"\bversion\s*(?:은|는|:|=)\s*(v[0-9][A-Za-z0-9]*)") or "v1alpha1"

    spec_fields = parse_fields(text, "spec")
    status_fields = parse_fields(text, "status")
    controller_enabled = not bool(re.search(r"controller\s*(?:는|은)?\s*(?:아직\s*)?(?:만들지\s*않|생성하지\s*않|false|없이)", text, re.I))

    return build_spec(
        kind=kind,
        domain=domain,
        group=group,
        version=version,
        spec_fields=spec_fields,
        status_fields=status_fields,
        controller_enabled=controller_enabled,
        responsibilities=parse_responsibilities(text),
    )


def build_spec(
    *,
    kind: str,
    domain: str,
    group: str,
    version: str,
    spec_fields: list[dict],
    status_fields: list[dict],
    controller_enabled: bool,
    responsibilities: list[str],
) -> dict:
    project_name = lower_camel_to_kebab(kind) + "-operator"
    module = f"{domain}/{project_name}"
    workspace = f"workspace/{project_name}"
    api_group = f"{group}.{domain}"

    result = {
        "project": {
            "name": project_name,
            "domain": domain,
            "module": module,
            "workspace": workspace,
        },
        "resource": {
            "group": group,
            "apiGroup": api_group,
            "version": version,
            "kind": kind,
            "plural": pluralize(lower_camel_to_kebab(kind).replace("-", "")),
            "scope": "Namespaced",
        },
        "spec": {
            "fields": spec_fields,
        },
        "status": {
            "fields": status_fields,
        },
        "controller": {
            "enabled": controller_enabled,
            "responsibilities": responsibilities,
        },
    }

    create_api = [
        "kubebuilder",
        "create",
        "api",
        "--group",
        group,
        "--version",
        version,
        "--kind",
        kind,
        "--resource",
    ]
    if not controller_enabled:
        create_api.append("--controller=false")

    result["generation"] = {
        "kubebuilderInit": [
            "kubebuilder",
            "init",
            "--domain",
            domain,
            "--repo",
            module,
        ],
        "kubebuilderCreateApi": create_api,
    }
    result["validation"] = {
        "commands": [
            "make generate",
            "make manifests",
            "make test",
        ],
    }
    return result


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_validated(prompt: str, default: str, validator, help_text: str) -> str:
    while True:
        value = sanitize_text(ask(prompt, default))
        if validator(value):
            return value
        print(f"입력값이 올바르지 않습니다: {value}")
        print(help_text)


def ask_fields(prompt: str, default: str) -> list[dict]:
    value = ask(prompt, default)
    fields = []
    for token in split_field_tokens(value):
        name, field_type = parse_field_token(token)
        if name and is_valid_field_name(name):
            fields.append(
                {
                    "name": name,
                    "type": field_type,
                    "description": default_description("spec" if "spec" in prompt else "status", name),
                }
            )
    return fields


def ask_multiline(prompt: str) -> list[str]:
    print(f"{prompt}을 한 줄씩 입력하세요. 빈 줄을 입력하면 종료합니다.")
    values: list[str] = []
    while True:
        value = sanitize_text(input("> ").strip())
        if not value:
            break
        values.append(value)
    return values


def suggest_kind(purpose: str) -> str:
    if "학습" in purpose or "훈련" in purpose:
        return "TrainingJob"
    lowered = purpose.lower()
    if "training" in lowered or "gpu" in lowered:
        return "TrainingJob"
    if "redis" in lowered or "캐시" in purpose:
        return "RedisCache"
    if "백업" in purpose or "backup" in lowered:
        return "BackupPolicy"
    words = [word for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", purpose) if word.lower() != "kubernetes"]
    if words:
        return "".join(word[:1].upper() + word[1:] for word in words[-2:])
    return "SampleResource"


def suggest_spec_fields(purpose: str) -> str:
    lowered = purpose.lower()
    if "redis" in lowered or "캐시" in purpose:
        return "size:int32, image:string, storageSize:string"
    if "학습" in purpose or "training" in lowered or "gpu" in lowered:
        return "image:string, gpuCount:int32, pvcName:string, datasetPath:string, outputPath:string"
    if "백업" in purpose or "backup" in lowered:
        return "targetNamespace:string, schedule:string, retentionDays:int32, pvcNames:[]string"
    return "name:string, image:string"


def suggest_status_fields(purpose: str) -> str:
    lowered = purpose.lower()
    if "redis" in lowered or "캐시" in purpose:
        return "phase:string, readyReplicas:int32, message:string"
    if "학습" in purpose or "training" in lowered or "gpu" in lowered:
        return "phase:string, jobName:string, podName:string, message:string"
    if "백업" in purpose or "backup" in lowered:
        return "phase:string, lastRunTime:string, message:string"
    return "phase:string, message:string"


def suggest_managed_resources(purpose: str) -> str:
    lowered = purpose.lower()
    if "redis" in lowered or "캐시" in purpose:
        return "StatefulSet, Service, PVC"
    if "학습" in purpose or "training" in lowered or "gpu" in lowered:
        return "Job, Pod, PVC"
    if "백업" in purpose or "backup" in lowered:
        return "CronJob, Job, PVC"
    return "Deployment, Service"


def find_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text, re.I)
    return match.group(1).strip(" .,`'\"") if match else ""


def parse_fields(text: str, section: str) -> list[dict]:
    pattern = rf"{section}\s*(?:필드|에는|은|는|:)?\s*(?:에는|은|는)?\s*([A-Za-z0-9_,:\s\[\]]+?)(?:를|을|가|로|\.|\n|$)"
    matches = re.findall(pattern, text, re.I)
    fields: list[dict] = []
    for match in matches:
        for token in split_field_tokens(match):
            name, field_type = parse_field_token(token)
            if name and not any(item["name"] == name for item in fields):
                fields.append(
                    {
                        "name": name,
                        "type": field_type,
                        "description": default_description(section, name),
                    }
                )
    return fields


def split_field_tokens(value: str) -> list[str]:
    cleaned = re.sub(r"\b(and|with|include|includes|포함한다|가진다)\b", ",", value, flags=re.I)
    return [token.strip(" ,.`'\"") for token in cleaned.split(",") if token.strip(" ,.`'\"")]


def parse_field_token(token: str) -> tuple[str, str]:
    if ":" in token:
        name, field_type = [part.strip() for part in token.split(":", 1)]
        return name, normalize_type(field_type)
    name = token.strip()
    return name, TYPE_HINTS.get(name, "string")


def sanitize_text(value: str) -> str:
    return "".join(ch for ch in value.strip() if ch.isprintable() and not (0xDC80 <= ord(ch) <= 0xDCFF))


def is_valid_kind(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Za-z0-9]*", value))


def is_valid_domain(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)+", value))


def is_valid_dns_label(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", value))


def is_valid_version(value: str) -> bool:
    return bool(re.fullmatch(r"v[0-9]+((alpha|beta)[0-9]+)?", value))


def is_valid_field_name(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z][A-Za-z0-9]*", value))


def normalize_resource_list(value: str) -> str:
    resources: list[str] = []
    for token in re.split(r"[,/\s]+", sanitize_text(value)):
        if not token:
            continue
        normalized = KNOWN_K8S_RESOURCES.get(token.lower())
        if normalized and normalized not in resources:
            resources.append(normalized)
    return ", ".join(resources)


def parse_responsibilities(text: str) -> list[str]:
    responsibilities: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip().strip(".")
        if not line:
            continue
        if re.search(r"(Operator를\s*만들고|domain\s*(?:은|는|:|=)|group\s*(?:은|는|:|=)|version\s*(?:은|는|:|=)|kind\s*(?:은|는|:|=))", line, re.I):
            continue
        if not re.search(r"(Controller|Job|Pod|GPU|nvidia\.com/gpu|spec\.|status\.)", line, re.I):
            continue
        if re.search(r"(?:만들지\s*않|생성하지\s*않|false|없이)", line, re.I):
            continue
        if re.match(r"^(spec|status)\s*(?:에는|은|는|:)", line, re.I):
            continue
        if line not in responsibilities:
            responsibilities.append(line)
    return responsibilities


def normalize_type(value: str) -> str:
    value = value.strip()
    aliases = {
        "int": "int32",
        "integer": "int32",
        "number": "int32",
        "str": "string",
        "bool": "bool",
        "boolean": "bool",
    }
    return aliases.get(value.lower(), value)


def default_description(section: str, name: str) -> str:
    if section == "spec":
        return f"Desired {name} value."
    return f"Observed {name} value."


def lower_camel_to_kebab(value: str) -> str:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", value)
    return value.lower()


def pluralize(value: str) -> str:
    if value.endswith("s"):
        return value + "es"
    if value.endswith("y"):
        return value[:-1] + "ies"
    return value + "s"


def render_yaml(value, indent: int = 0) -> str:
    lines: list[str] = []
    write_yaml(lines, value, indent)
    return "\n".join(lines) + "\n"


def write_yaml(lines: list[str], value, indent: int) -> None:
    prefix = " " * indent
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{key}:")
                write_yaml(lines, child, indent + 2)
            else:
                lines.append(f"{prefix}{key}: {format_scalar(child)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                lines.append(f"{prefix}- {next(iter(item))}: {format_scalar(next(iter(item.values())))}")
                for key, child in list(item.items())[1:]:
                    if isinstance(child, (dict, list)):
                        lines.append(f"{prefix}  {key}:")
                        write_yaml(lines, child, indent + 4)
                    else:
                        lines.append(f"{prefix}  {key}: {format_scalar(child)}")
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                write_yaml(lines, item, indent + 2)
            else:
                lines.append(f"{prefix}- {format_scalar(item)}")


def format_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    text = str(value)
    if text == "" or text.startswith(("{", "[", "*", "&")) or ": " in text:
        return repr(text)
    return text


if __name__ == "__main__":
    raise SystemExit(main())
