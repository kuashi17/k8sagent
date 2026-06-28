"""Capability support levels exposed to Agent and Web result contracts."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict


SUPPORT_PATH = Path(__file__).resolve().parents[1] / "config" / "capability-support.yaml"


class CapabilitySupport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource: str
    level: Literal["stable", "beta", "experimental"]
    evidenceRun: int | None = None
    explanation: str


@lru_cache(maxsize=1)
def load_capability_support() -> dict[str, CapabilitySupport]:
    data = yaml.safe_load(SUPPORT_PATH.read_text(encoding="utf-8")) or {}
    evidence_run = data.get("evidenceRun")
    return {
        str(resource): CapabilitySupport(
            resource=str(resource),
            level=str(level),
            evidenceRun=int(evidence_run) if evidence_run else None,
            explanation=support_explanation(str(level)),
        )
        for resource, level in (data.get("levels") or {}).items()
    }


def support_for(resources: list[str]) -> list[dict[str, Any]]:
    support = load_capability_support()
    return [
        (support.get(resource)
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
