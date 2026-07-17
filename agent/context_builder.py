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
)
from agent.tools.spec_generator import (
    extract_k8s_resources,
    parse_api,
    parse_controller,
    parse_fields,
)


RetrievalFunction = Callable[[str, int, str], dict[str, Any]]


def build_requirement_context(
    requirement_path: Path,
    requirement_text: str,
    workspace: str,
    artifact_dir: str,
    retrieve: RetrievalFunction,
    rag_limit: int,
) -> dict[str, Any]:
    # 실행 판단에 필요한 값은 먼저 결정론적 파서로 정규화한다.
    # 검색 문서는 판단을 보완하는 근거이며 API·필드·리소스를 덮어쓰지 않는다.
    retrieval_started = time.perf_counter()
    summary = summarize_requirement(requirement_text)
    intent = analyze_requirement_intent(requirement_text)
    kind = summary.get("kind") or "operator"
    kind_slug = kind.lower()
    artifact_root = Path(artifact_dir)
    operator_spec = artifact_root / f"{kind_slug}-operator-spec.yaml"
    isolated_outputs = (
        Path(workspace) != Path("workspace/generated-operators")
        or artifact_root != Path("generated")
    )
    retrieval = retrieve(requirement_text, rag_limit, "requirement")
    retrieved = retrieval["selectedContext"]
    return {
        "requirement": str(requirement_path),
        "requirementSummary": summary,
        "intentAnalysis": intent,
        "missingInformation": missing_information(summary, requirement_text),
        "retrievedKnowledge": retrieved,
        "retrievalDetails": retrieval,
        "workspace": workspace,
        "isolatedOutputs": isolated_outputs,
        "targetProjectDir": target_project_dir(
            workspace,
            kind,
            str(operator_spec),
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
    conflicts = detect_requirement_conflicts(text)
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
        "requirementConflicts": conflicts,
        "shortSummary": (
            f"{kind or 'Unknown'} Operator 요구사항: "
            f"{', '.join(managed) or '관리 리소스 미확인'} 관리 흐름."
        ),
    }


def missing_information(summary: dict[str, Any], text: str) -> list[str]:
    # 필수 정보와 모순을 LLM 호출 전에 차단해 임의 보완과 불필요한 Tool 실행을 막는다.
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
    missing.extend(
        f"conflicting requirement: {item}"
        for item in summary.get("requirementConflicts") or []
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
    questions.extend(
        f"{item.removeprefix('conflicting requirement: ')} 중 어느 동작을 원하는지 하나로 정해 주세요."
        for item in missing
        if item.startswith("conflicting requirement: ")
    )
    managed = summary.get("managedResources") or []
    if managed and "status fields" in missing:
        questions.append(f"{', '.join(managed)} 상태 중 어떤 값을 status에 반영할까요?")
    return questions


def detect_requirement_conflicts(text: str) -> list[str]:
    """Find explicit write/read and deletion-policy contradictions.

    This gate is intentionally conservative: it only stops combinations that
    cannot be implemented safely without choosing one of two opposite user
    instructions. Ordinary exclusions such as "Service는 만들지 마세요"
    remain valid requirements.
    """
    normalized = " ".join(text.split())
    conflicts: list[str] = []
    for resource in dict.fromkeys(extract_k8s_resources(normalized)):
        token = re.escape(resource)
        repeated_write = re.search(
            rf"{token}[^.!?]{{0,80}}(?:생성|만들|관리|수정|갱신|변경)[^.!?]{{0,30}}"
            rf"(?:하지\s*(?:않|말|마)|하면\s*안)[^.!?]{{0,100}}"
            rf"{token}[^.!?]{{0,50}}(?:생성|만들|관리|수정|갱신|변경|복구)",
            normalized,
            re.IGNORECASE,
        )
        if repeated_write:
            conflicts.append(f"{resource} 변경 금지와 변경 요청이 동시에 있습니다.")

        resource_sentences = [
            sentence
            for sentence in re.split(r"[.!?]", normalized)
            if resource.lower() in sentence.lower()
        ]
        scoped = " ".join(resource_sentences)
        if (
            any(token in scoped for token in ("유지", "남겨", "삭제하지", "자동 삭제하지"))
            and any(token in scoped for token in ("함께 삭제", "도 삭제", "삭제되어야"))
        ):
            conflicts.append(f"{resource} 삭제 시 유지와 함께 삭제가 동시에 요청됐습니다.")
        if (
            any(token in scoped for token in ("읽기만", "조회만", "read-only", "수정하지"))
            and any(token in scoped for token in ("복구", "원래 상태로", "spec 기준으로 되돌"))
        ):
            conflicts.append(f"{resource} 읽기 전용과 외부 변경 복구가 동시에 요청됐습니다.")
    return list(dict.fromkeys(conflicts))


def target_project_dir(
    workspace: str,
    kind: str,
    operator_spec: str,
) -> str:
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
