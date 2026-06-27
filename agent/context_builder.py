"""Requirement parsing and planning context assembly."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable

import yaml

from agent.requirement_analyzer import (
    analyze_requirement_intent,
    infer_managed_resources,
    select_profile_hint,
)


RetrievalFunction = Callable[[str, int, str], dict[str, Any]]


def build_requirement_context(
    requirement_path: Path,
    requirement_text: str,
    profile_path: str | None,
    profile: dict[str, Any],
    workspace: str,
    retrieve: RetrievalFunction,
    rag_limit: int,
    allow_profile_hints: bool = True,
) -> dict[str, Any]:
    retrieval_started = time.perf_counter()
    summary = summarize_requirement(requirement_text)
    intent = analyze_requirement_intent(requirement_text)
    profile_hint = select_profile_hint(
        requirement_text,
        profile_path,
        profile,
        allow_auto_hint=allow_profile_hints,
    )
    kind = summary.get("kind") or "operator"
    kind_slug = kind.lower()
    selected_profile = profile_hint["selectedProfile"]
    retrieval = retrieve(requirement_text, rag_limit, "requirement")
    retrieved = retrieval["selectedContext"]
    return {
        "requirement": str(requirement_path),
        "requirementSummary": summary,
        "intentAnalysis": intent,
        "missingInformation": missing_information(summary, requirement_text),
        "retrievedKnowledge": retrieved,
        "retrievalDetails": retrieval,
        "selectedProfile": selected_profile,
        "profileCandidates": profile_hint["profileCandidates"],
        "workspace": workspace,
        "targetProjectDir": target_project_dir(
            workspace,
            kind,
            kind_slug,
            selected_profile,
        ),
        "generatedFiles": {
            "operatorSpec": f"generated/{kind_slug}-operator-spec.yaml",
            "capabilityProposal": (
                f"generated/{kind_slug}-capability-proposal.yaml"
            ),
            "commandPlan": f"generated/{kind_slug}-command-plan.md",
        },
        "timings": {
            "ragRetrievalSeconds": round(
                time.perf_counter() - retrieval_started,
                3,
            )
        },
    }


def summarize_requirement(text: str) -> dict[str, Any]:
    kind = find_value(text, r"kind\s*(?:은|는|:|=)\s*([A-Z][A-Za-z0-9]*)") or find_value(
        text,
        r"([A-Z][A-Za-z0-9]*)\s*라는\s+Kubernetes Custom Resource",
    )
    domain = find_value(text, r"domain\s*(?:은|는|:|=)\s*([a-z0-9.-]+\.[a-z0-9.-]+)")
    group = find_value(text, r"group\s*(?:은|는|:|=)\s*([a-z][a-z0-9-]*)")
    version = find_value(text, r"version\s*(?:은|는|:|=)\s*(v[0-9]+(?:alpha[0-9]+|beta[0-9]+)?)")
    managed = infer_managed_resources(text)
    spec_fields = parse_field_names(text, "spec")
    status_fields = parse_field_names(text, "status")
    return {
        "kind": kind,
        "domain": domain,
        "group": group,
        "version": version,
        "managedResources": managed,
        "specFields": spec_fields,
        "statusFields": status_fields,
        "shortSummary": (
            f"{kind or 'Unknown'} Operator 요구사항: "
            f"{', '.join(managed) or '관리 리소스 미확인'} 관리 흐름."
        ),
    }


def missing_information(summary: dict[str, Any], text: str) -> list[str]:
    checks = {
        "kind": summary.get("kind"),
        "domain": summary.get("domain"),
        "group": summary.get("group"),
        "version": summary.get("version"),
        "spec fields": summary.get("specFields"),
        "status fields": summary.get("statusFields"),
        "managed Kubernetes resource": summary.get("managedResources"),
    }
    return [name for name, value in checks.items() if not value]


def clarifying_questions(
    missing: list[str],
    summary: dict[str, Any],
) -> list[str]:
    question_map = {
        "kind": "Custom Resource 이름(kind)을 무엇으로 할까요? 예: BackupPolicy, WebService, SecretSync",
        "domain": "API domain은 무엇으로 할까요? 예: sample.io, platform.internal",
        "group": "API group은 무엇으로 할까요? 예: app, batch, security",
        "version": "API version은 무엇으로 할까요? 보통 처음에는 v1alpha1을 사용합니다.",
        "spec fields": "사용자가 Custom Resource에 입력해야 하는 spec 필드는 무엇인가요?",
        "status fields": "kubectl로 확인하고 싶은 status 필드는 무엇인가요?",
        "managed Kubernetes resource": (
            "Controller가 생성하거나 관리할 Kubernetes 리소스는 무엇인가요? "
            "예: ConfigMap, Secret, Deployment, Job"
        ),
        "validation commands": "검증 명령은 make generate, make manifests, make test를 사용해도 될까요?",
    }
    questions = [question_map[item] for item in missing if item in question_map]
    managed = summary.get("managedResources") or []
    if managed and "status fields" in missing:
        questions.append(f"{', '.join(managed)} 상태 중 어떤 값을 status에 반영할까요?")
    return questions


def parse_field_names(text: str, section: str) -> list[str]:
    match = re.search(
        rf"{section}\s*에는.*?(?=\n\n|status에는|Controller는|검증 명령|$)",
        text,
        flags=re.DOTALL,
    )
    block = match.group(0) if match else ""
    listed = re.findall(
        r"^\s*-\s*([a-z][A-Za-z0-9]*)\s*:",
        block,
        flags=re.MULTILINE,
    )
    if listed:
        return listed
    inline = re.search(
        rf"{section}\s*에는\s+(.+?)을\s*포함한다",
        text,
        flags=re.DOTALL,
    )
    if not inline:
        return []
    return [
        match.group(1)
        for item in re.split(r"\s*,\s*", inline.group(1))
        if (
            match := re.match(
                r"\s*([a-z][A-Za-z0-9]*)\s*:",
                item,
            )
        )
    ]


def target_project_dir(
    workspace: str,
    kind: str,
    kind_slug: str,
    selected_profile: dict[str, Any],
) -> str:
    capability = selected_profile.get("kindDeployment") or {}
    profile_project = str(capability.get("project") or "")
    if profile_project:
        return profile_project
    return str(
        Path(workspace)
        / infer_project_name(
            kind,
            f"generated/{kind_slug}-operator-spec.yaml",
        )
    )


def find_value(text: str, pattern: str) -> str:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else ""


def infer_project_name(kind: str, spec_path: str) -> str:
    path = Path(spec_path)
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                project = data.get("project") or {}
                if project.get("name"):
                    return str(project["name"])
        except yaml.YAMLError:
            pass
    return camel_to_kebab(kind) + "-operator" if kind else "operator"


def camel_to_kebab(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", value).lower()


def extract_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key) if isinstance(data, dict) else []
    return value if isinstance(value, list) else []


def extract_tool_call_plan(data: dict[str, Any]) -> list[dict[str, Any]]:
    value = data.get("toolCalls") if isinstance(data, dict) else []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
