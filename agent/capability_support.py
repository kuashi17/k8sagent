"""Capability support levels exposed to Agent and Web result contracts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent.tools.resource_catalog import load_resource_catalog


SUPPORT_PATH = Path(__file__).resolve().parents[1] / "config" / "capability-support.yaml"


class CapabilitySupport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource: str
    level: Literal["stable", "beta", "experimental"]
    evidenceRun: int | None = None
    lastValidatedAt: str = ""
    evidenceBased: bool = True
    evidence: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    explanation: str


@lru_cache(maxsize=1)
def load_capability_support() -> dict[str, CapabilitySupport]:
    data = yaml.safe_load(SUPPORT_PATH.read_text(encoding="utf-8")) or {}
    evidence_run = data.get("evidenceRun")
    last_validated = str(data.get("lastValidatedAt") or "")
    evidence_source = str(data.get("evidenceSource") or "")
    limitations = data.get("limitations") or {}
    return {
        str(resource): CapabilitySupport(
            resource=str(resource),
            level=str(level),
            evidenceRun=int(evidence_run) if evidence_run else None,
            lastValidatedAt=last_validated,
            evidence={
                "source": evidence_source,
                "criteria": grade_criteria(str(level)),
            },
            limitations=[
                str(item) for item in limitations.get(resource, [])
            ],
            explanation=support_explanation(str(level)),
        )
        for resource, level in (data.get("levels") or {}).items()
    }


def support_for(resources: list[str]) -> list[dict[str, Any]]:
    support = load_capability_support()
    catalog = load_resource_catalog().by_name()
    return [
        (support.get(
            catalog.get(resource).kind if catalog.get(resource) else resource
        )
        or CapabilitySupport(
            resource=resource,
            level="experimental",
            explanation=support_explanation("experimental"),
        )).model_dump(mode="json")
        for resource in resources
    ]


def support_explanation(level: str) -> str:
    return {
        "stable": "컴파일, kind lifecycle, drift 복구 증거가 있습니다.",
        "beta": "컴파일과 기본 lifecycle 증거가 있으나 일부 검증이 제한됩니다.",
        "experimental": "계약 검증 단계이며 실제 kind 증거가 충분하지 않습니다.",
    }[level]


def grade_criteria(level: str) -> list[str]:
    if level == "stable":
        return [
            "compile",
            "kindLifecycle",
            "idempotency",
            "driftRecovery",
            "rbacLeastPrivilege",
            "deletionPolicy",
            "stateMachine",
        ]
    if level == "beta":
        return ["compile", "kindLifecycle"]
    return ["catalogSchema"]
