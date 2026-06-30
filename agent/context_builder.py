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
from agent.tools.spec_generator import parse_api, parse_controller, parse_fields


RetrievalFunction = Callable[[str, int, str], dict[str, Any]]


def build_requirement_context(
    requirement_path: Path,
    requirement_text: str,
    profile_path: str | None,
    profile: dict[str, Any],
    workspace: str,
    artifact_dir: str,
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
    artifact_root = Path(artifact_dir)
    operator_spec = artifact_root / f"{kind_slug}-operator-spec.yaml"
    isolated_outputs = (
        Path(workspace) != Path("workspace/generated-operators")
        or artifact_root != Path("generated")
    )
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
        "isolatedOutputs": isolated_outputs,
        "targetProjectDir": target_project_dir(
            workspace,
            kind,
            kind_slug,
            selected_profile,
            str(operator_spec),
            isolated_outputs,
        ),
        "generatedFiles": {
            "operatorSpec": str(operator_spec),
            "capabilityProposal": (
                str(artifact_root / f"{kind_slug}-capability-proposal.yaml")
            ),
            "commandPlan": str(
                artifact_root / f"{kind_slug}-command-plan.md"
            ),
        },
        "timings": {
            "ragRetrievalSeconds": round(
                time.perf_counter() - retrieval_started,
                3,
            )
        },
    }


def summarize_requirement(text: str) -> dict[str, Any]:
    api = parse_api(text, [])
    controller = parse_controller(text, [])
    kind = api["kind"]
    domain = api["domain"]
    group = api["group"]
    version = api["version"]
    managed = controller.get("managedResources") or infer_managed_resources(text)
    observed = controller.get("observedResources") or []
    parsed_spec = parse_fields(text, "spec", [])
    parsed_status = parse_fields(text, "status", [])
    spec_fields = [item["name"] for item in parsed_spec]
    status_fields = [item["name"] for item in parsed_status]
    ambiguous_types = [
        f"{section}.{item['name']}"
        for section, fields in (
            ("spec", parsed_spec),
            ("status", parsed_status),
        )
        for item in fields
        if item.get("needsConfirmation")
    ]
    return {
        "kind": kind,
        "domain": domain,
        "group": group,
        "version": version,
        "managedResources": managed,
        "observedResources": observed,
        "resourcePolicies": controller.get("resourcePolicies") or [],
        "specFields": spec_fields,
        "statusFields": status_fields,
        "ambiguousFieldTypes": ambiguous_types,
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
        "managed or observed Kubernetes resource": (
            summary.get("managedResources")
            or summary.get("observedResources")
        ),
    }
    missing = [name for name, value in checks.items() if not value]
    missing.extend(
        f"field type: {item}"
        for item in summary.get("ambiguousFieldTypes") or []
    )
    return missing


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
        "managed or observed Kubernetes resource": (
            "Controller가 생성·관리하거나 조회할 Kubernetes 리소스는 무엇인가요?"
        ),
        "validation commands": "검증 명령은 make generate, make manifests, make test를 사용해도 될까요?",
    }
    questions = [question_map[item] for item in missing if item in question_map]
    questions.extend(
        f"{item.removeprefix('field type: ')} 필드 타입을 확인해 주세요."
        for item in missing
        if item.startswith("field type: ")
    )
    managed = summary.get("managedResources") or []
    if managed and "status fields" in missing:
        questions.append(f"{', '.join(managed)} 상태 중 어떤 값을 status에 반영할까요?")
    return questions


def target_project_dir(
    workspace: str,
    kind: str,
    kind_slug: str,
    selected_profile: dict[str, Any],
    operator_spec: str,
    isolated_outputs: bool = False,
) -> str:
    capability = selected_profile.get("kindDeployment") or {}
    profile_project = str(capability.get("project") or "")
    if profile_project and not isolated_outputs:
        return profile_project
    return str(
        Path(workspace)
        / infer_project_name(
            kind,
            operator_spec,
        )
    )


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
