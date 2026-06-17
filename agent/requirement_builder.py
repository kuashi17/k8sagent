#!/usr/bin/env python3
"""Build a complete Operator requirement text from a rough user draft."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.requirement_analyzer import analyze_requirement_intent, infer_managed_resources


RESOURCE_DEFAULTS = {
    "ConfigMap": {
        "kind": "ConfigPolicy",
        "purpose": "애플리케이션 설정 값을 ConfigMap으로 관리한다.",
        "spec": [
            ("appName", "string", "설정을 적용할 애플리케이션 이름"),
            ("configData", "map[string]string", "ConfigMap data에 저장할 설정 값"),
            ("enabled", "bool", "설정 활성화 여부"),
        ],
        "status": [
            ("phase", "string", "현재 처리 상태"),
            ("configMapName", "string", "생성 또는 갱신된 ConfigMap 이름"),
            ("message", "string", "현재 상태 설명 또는 오류 메시지"),
        ],
        "mappings": [
            "spec.configData -> ConfigMap.data",
            "spec.enabled=false -> ConfigMap을 생성하지 않거나 기존 ConfigMap을 삭제",
        ],
        "statusRules": [
            "status.phase는 ConfigMap 생성 여부와 spec.enabled 값을 기준으로 갱신한다.",
            "status.configMapName은 생성 또는 갱신한 ConfigMap 이름으로 갱신한다.",
        ],
        "rbac": ["core/configmaps"],
    },
    "Secret": {
        "kind": "SecretSync",
        "purpose": "사용자가 입력한 값을 Kubernetes Secret으로 관리한다.",
        "spec": [
            ("secretName", "string", "생성할 Secret 이름"),
            ("data", "map[string]string", "Secret stringData에 반영할 key/value 값"),
            ("enabled", "bool", "Secret 생성 활성화 여부"),
        ],
        "status": [
            ("phase", "string", "현재 처리 상태"),
            ("secretName", "string", "생성 또는 갱신된 Secret 이름"),
            ("message", "string", "현재 상태 설명 또는 오류 메시지"),
        ],
        "mappings": ["spec.data -> Secret.stringData", "spec.secretName -> Secret.metadata.name"],
        "statusRules": ["status.phase는 Secret 생성/갱신 여부를 기준으로 갱신한다."],
        "rbac": ["core/secrets"],
    },
    "CronJob": {
        "kind": "ScheduledTask",
        "purpose": "정해진 스케줄에 따라 컨테이너 작업을 CronJob으로 실행한다.",
        "spec": [
            ("schedule", "string", "CronJob 실행 스케줄"),
            ("image", "string", "실행할 컨테이너 이미지"),
            ("command", "[]string", "컨테이너에서 실행할 명령"),
            ("suspend", "bool", "스케줄 일시 중지 여부"),
        ],
        "status": [
            ("phase", "string", "현재 처리 상태"),
            ("cronJobName", "string", "생성 또는 갱신된 CronJob 이름"),
            ("lastScheduleTime", "metav1.Time", "마지막 스케줄 실행 시각"),
            ("message", "string", "현재 상태 설명 또는 오류 메시지"),
        ],
        "mappings": [
            "spec.schedule -> CronJob.spec.schedule",
            "spec.image -> CronJob JobTemplate container image",
            "spec.command -> CronJob JobTemplate container command",
            "spec.suspend -> CronJob.spec.suspend",
        ],
        "statusRules": ["status.phase와 status.lastScheduleTime은 CronJob 상태를 기준으로 갱신한다."],
        "rbac": ["batch/cronjobs"],
    },
    "Deployment": {
        "kind": "WebService",
        "purpose": "애플리케이션 컨테이너를 Deployment와 Service로 배포한다.",
        "spec": [
            ("appName", "string", "배포할 애플리케이션 이름"),
            ("image", "string", "Deployment에 사용할 컨테이너 이미지"),
            ("replicas", "int32", "Deployment replica 수"),
            ("port", "int32", "Service와 컨테이너 포트"),
        ],
        "status": [
            ("phase", "string", "현재 처리 상태"),
            ("deploymentName", "string", "생성 또는 갱신된 Deployment 이름"),
            ("serviceName", "string", "생성 또는 갱신된 Service 이름"),
            ("readyReplicas", "int32", "준비된 Pod replica 수"),
            ("message", "string", "현재 상태 설명 또는 오류 메시지"),
        ],
        "mappings": [
            "spec.image -> Deployment container image",
            "spec.replicas -> Deployment.spec.replicas",
            "spec.port -> Deployment containerPort and Service port",
        ],
        "statusRules": ["status.readyReplicas는 Deployment.status.readyReplicas를 기준으로 갱신한다."],
        "rbac": ["apps/deployments", "core/services", "core/pods"],
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a complete Operator requirement text from a rough draft.")
    parser.add_argument("--draft", default="", help="Rough natural language request.")
    parser.add_argument("--input", help="File containing a rough natural language request.")
    parser.add_argument("--output", help="Output requirement text path.")
    parser.add_argument("--assume-defaults", action="store_true", help="Fill missing details with safe defaults instead of asking.")
    parser.add_argument("--print-questions", action="store_true", help="Print clarifying questions before writing the file.")
    args = parser.parse_args()

    draft = args.draft
    if args.input:
        draft = Path(args.input).read_text(encoding="utf-8")
    if not draft.strip():
        draft = ask("어떤 Operator를 만들고 싶나요?", "애플리케이션 설정을 ConfigMap으로 관리하고 싶다")

    requirement = build_requirement(draft, assume_defaults=args.assume_defaults)
    output = Path(args.output) if args.output else default_output_path(requirement)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(requirement["text"], encoding="utf-8")

    if args.print_questions:
        print("Clarifying questions:")
        for item in requirement["questions"]:
            print(f"- {item}")
        print()
    print(f"Requirement written: {output}")
    print(f"Kind: {requirement['kind']}")
    print(f"Managed resources: {', '.join(requirement['managedResources']) or 'unknown'}")
    return 0


def build_requirement(draft: str, *, assume_defaults: bool) -> dict[str, Any]:
    resources = infer_managed_resources(draft)
    primary_resource = choose_primary_resource(resources)
    defaults = RESOURCE_DEFAULTS.get(primary_resource, RESOURCE_DEFAULTS["ConfigMap"])
    kind = extract_kind(draft) or value_or_ask("Custom Resource Kind", defaults["kind"], assume_defaults)
    domain = extract_value(draft, "domain") or value_or_ask("API domain", "sample.io", assume_defaults)
    group = extract_value(draft, "group") or value_or_ask("API group", group_from_resource(primary_resource), assume_defaults)
    version = extract_value(draft, "version") or value_or_ask("API version", "v1alpha1", assume_defaults)
    purpose = extract_purpose(draft) or value_or_ask("Operator purpose", defaults["purpose"], assume_defaults)
    spec_fields = parse_field_lines(draft, "spec") or defaults["spec"]
    status_fields = parse_field_lines(draft, "status") or defaults["status"]
    managed_resources = resources or [primary_resource]
    mappings = defaults["mappings"]
    status_rules = defaults["statusRules"]
    rbac = defaults["rbac"]
    questions = clarifying_questions(draft, kind, domain, group, version, spec_fields, status_fields, managed_resources)
    return {
        "kind": kind,
        "managedResources": managed_resources,
        "questions": questions,
        "intentAnalysis": analyze_requirement_intent(draft),
        "text": render_requirement(
            kind=kind,
            purpose=purpose,
            domain=domain,
            group=group,
            version=version,
            spec_fields=spec_fields,
            status_fields=status_fields,
            managed_resources=managed_resources,
            mappings=mappings,
            status_rules=status_rules,
            rbac=rbac,
        ),
    }


def render_requirement(
    *,
    kind: str,
    purpose: str,
    domain: str,
    group: str,
    version: str,
    spec_fields: list[tuple[str, str, str]],
    status_fields: list[tuple[str, str, str]],
    managed_resources: list[str],
    mappings: list[str],
    status_rules: list[str],
    rbac: list[str],
) -> str:
    sample_name = camel_to_kebab(kind) + "-sample"
    lines = [
        f"{kind}라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다.",
        "",
        f"이 Operator의 목적은 {purpose}",
        "",
        f"domain은 {domain}, group은 {group}, version은 {version}, kind는 {kind}로 한다.",
        "",
        "spec에는 다음 필드를 포함한다.",
        *[f"- {name}:{field_type} - {description}" for name, field_type, description in spec_fields],
        "",
        "status에는 다음 필드를 포함한다.",
        *[f"- {name}:{field_type} - {description}" for name, field_type, description in status_fields],
        "",
        f"Controller는 {kind} Custom Resource 변경을 감지한다.",
        f"Controller는 {', '.join(managed_resources)} 리소스를 생성/수정/삭제한다.",
        "",
        "Controller는 다음 규칙에 따라 spec 값을 관리 리소스에 반영한다.",
        *[f"- {item}" for item in mappings],
        "",
        f"Controller는 {', '.join(managed_resources)} 상태를 조회하여 status를 갱신한다.",
        *[f"- {item}" for item in status_rules],
        "",
        f"{kind}가 삭제되면 ownerReference 정책에 따라 하위 리소스를 정리한다.",
        "",
        "필요한 RBAC 권한은 다음 리소스를 기준으로 추론한다.",
        *[f"- {item}" for item in rbac],
        "",
        "검증 명령은 다음을 사용한다.",
        "- make generate",
        "- make manifests",
        "- make test",
        "",
        "샘플 Custom Resource는 다음 값을 사용한다.",
        f"apiVersion: {group}.{domain}/{version}",
        f"kind: {kind}",
        "metadata:",
        f"  name: {sample_name}",
        "spec:",
        *[f"  {name}: {sample_value(field_type, name)}" for name, field_type, _ in spec_fields],
        "",
    ]
    return "\n".join(lines)


def clarifying_questions(
    draft: str,
    kind: str,
    domain: str,
    group: str,
    version: str,
    spec_fields: list[tuple[str, str, str]],
    status_fields: list[tuple[str, str, str]],
    managed_resources: list[str],
) -> list[str]:
    questions = []
    if not extract_kind(draft):
        questions.append(f"Custom Resource Kind를 `{kind}`로 진행해도 될까요?")
    if not extract_value(draft, "domain"):
        questions.append(f"API domain을 `{domain}`로 사용해도 될까요?")
    if not extract_value(draft, "group"):
        questions.append(f"API group을 `{group}`로 사용해도 될까요?")
    if not extract_value(draft, "version"):
        questions.append(f"API version을 `{version}`로 사용해도 될까요?")
    if not parse_field_lines(draft, "spec"):
        questions.append("사용자가 입력해야 하는 spec 필드가 충분한가요? 필요하면 필드를 추가하세요.")
    if not parse_field_lines(draft, "status"):
        questions.append("kubectl로 확인하고 싶은 status 필드가 충분한가요?")
    if not managed_resources:
        questions.append("Controller가 생성/관리할 Kubernetes 리소스는 무엇인가요?")
    return questions


def choose_primary_resource(resources: list[str]) -> str:
    if "Deployment" in resources:
        return "Deployment"
    for candidate in ("CronJob", "Secret", "ConfigMap", "Job", "StatefulSet", "Service"):
        if candidate in resources:
            return candidate
    return "ConfigMap"


def extract_kind(text: str) -> str:
    patterns = [
        r"\bkind\s*(?:은|는|:|=)\s*([A-Z][A-Za-z0-9]*)",
        r"([A-Z][A-Za-z0-9]*)\s*라는\s+Kubernetes Custom Resource",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return ""


def extract_value(text: str, key: str) -> str:
    pattern = rf"\b{re.escape(key)}\s*(?:은|는|:|=)\s*([A-Za-z0-9_.-]+)"
    match = re.search(pattern, text)
    return match.group(1) if match else ""


def extract_purpose(text: str) -> str:
    match = re.search(r"목적은\s*(.+?)(?:다\.|\n|$)", text)
    return match.group(1).strip() + "다." if match else ""


def parse_field_lines(text: str, section: str) -> list[tuple[str, str, str]]:
    match = re.search(rf"{section}\s*에는.*?(?=\n\n|status에는|Controller는|$)", text, flags=re.DOTALL)
    block = match.group(0) if match else ""
    fields: list[tuple[str, str, str]] = []
    for name, field_type, description in re.findall(r"^\s*-\s*([a-z][A-Za-z0-9]*)\s*:\s*([^\s-]+)\s*-?\s*(.*)$", block, flags=re.MULTILINE):
        fields.append((name, field_type, description or f"{name} 값"))
    return fields


def value_or_ask(label: str, default: str, assume_defaults: bool) -> str:
    if assume_defaults:
        return default
    return ask(label, default)


def ask(prompt: str, default: str) -> str:
    value = input(f"{prompt} [{default}]: ").strip()
    return value or default


def group_from_resource(resource: str) -> str:
    mapping = {
        "ConfigMap": "config",
        "Secret": "security",
        "CronJob": "batch",
        "Deployment": "apps",
        "Job": "batch",
    }
    return mapping.get(resource, "sample")


def sample_value(field_type: str, name: str) -> str:
    if field_type == "string":
        if "image" in name.lower():
            return "nginx:latest"
        if "schedule" in name.lower():
            return '"*/5 * * * *"'
        return f"{camel_to_kebab(name)}-sample"
    if field_type in {"int", "int32", "int64"}:
        return "1"
    if field_type in {"bool", "boolean"}:
        return "true"
    if field_type == "map[string]string":
        return "{EXAMPLE_KEY: example-value}"
    if field_type == "[]string":
        return '["echo", "hello"]'
    if field_type == "metav1.Time":
        return "null"
    return "example"


def camel_to_kebab(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", value).lower()


def default_output_path(requirement: dict[str, Any]) -> Path:
    slug = camel_to_kebab(requirement["kind"]) or datetime.now().strftime("operator-%Y%m%d%H%M%S")
    return Path("requirements") / f"{slug}.txt"


if __name__ == "__main__":
    raise SystemExit(main())
