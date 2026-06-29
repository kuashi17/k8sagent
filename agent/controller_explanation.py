"""Create beginner-facing explanations from capability contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.tools.controller_ir import ReconcileStrategy
from agent.tools.resource_catalog import load_resource_catalog


def build_controller_explanation(
    summary: dict[str, Any],
    capability_support: list[dict[str, Any]],
) -> dict[str, Any]:
    requirement = summary.get("requirementSummary") or {}
    kind = str(requirement.get("kind") or "Custom Resource")
    version = str(requirement.get("version") or "v1alpha1")
    managed = [
        str(item) for item in requirement.get("managedResources") or []
    ]
    observed = [
        str(item) for item in requirement.get("observedResources") or []
    ]
    resources = unique(managed + observed)
    policies = {
        str(item.get("kind")): item
        for item in requirement.get("resourcePolicies") or []
        if isinstance(item, dict)
    }
    catalog = load_resource_catalog().by_name()
    watches = [f"{kind} 생성·수정·삭제 요청"]
    rbac = []
    deletion = []
    for raw in resources:
        definition = catalog.get(raw)
        if not definition:
            watches.append(f"{raw} 상태 변화(실험적 capability)")
            rbac.append(f"{raw}: 승인된 capability 계약의 권한만 사용합니다.")
            deletion.append(f"{raw}: 승인된 삭제 정책을 확인해야 합니다.")
            continue
        policy = policies.get(raw) or {}
        strategy = str(
            policy.get("strategy") or definition.strategy.value
        )
        ownership = str(
            policy.get("ownership") or definition.ownership.value
        )
        deletion_policy = str(
            policy.get("deletionPolicy")
            or definition.deletionPolicy.value
        )
        watches.append(
            f"{definition.kind} 상태 변화(조회 전용)"
            if strategy == ReconcileStrategy.READ_ONLY.value
            else f"{definition.kind} 상태 변화와 외부 drift"
        )
        verbs = (
            "get/list/watch"
            if strategy == ReconcileStrategy.READ_ONLY.value
            else (
                "get/list/watch/update/patch"
                if strategy == ReconcileStrategy.PATCH_EXISTING.value
                else "get/list/watch/create/update/patch/delete"
            )
        )
        group = (
            definition.apiVersion.split("/", 1)[0]
            if "/" in definition.apiVersion
            else "core"
        )
        rbac.append(
            f"{definition.kind}: {group}/{definition.plural or definition.kind.lower()}에 "
            f"{verbs} 권한이 필요합니다."
        )
        deletion.append(
            f"{definition.kind}: ownership={ownership}, "
            f"deletion={deletion_policy}."
        )
    generated = summary.get("generatedFiles") or {}
    target = str(summary.get("targetProjectDir") or "")
    kind_file = kind.lower()
    first_files = unique(
        [
            str(generated.get("operatorSpec") or ""),
            (
                str(Path(target) / "internal" / "controller" / f"{kind_file}_controller.go")
                if target
                else ""
            ),
            (
                str(Path(target) / "api" / version / f"{kind_file}_types.go")
                if target
                else ""
            ),
            str(generated.get("commandPlan") or ""),
        ]
    )
    limitations = unique(
        [
            str(value)
            for item in capability_support
            for value in item.get("limitations") or []
        ]
    )
    relationships = []
    if {"Deployment", "Service"}.issubset(set(resources)):
        relationships.append(
            "Service selector와 Deployment Pod template label을 같은 식별자로 유지해 Service가 생성된 Pod를 선택합니다."
        )
    return {
        "watches": watches,
        "rbacReasons": rbac,
        "deletionBehavior": deletion,
        "firstFiles": first_files,
        "validationLevels": capability_support,
        "limitations": limitations,
        "relationships": relationships,
    }


def unique(values: list[str]) -> list[str]:
    return [item for item in dict.fromkeys(values) if item]
