#!/usr/bin/env python3
"""Requirement intent analysis for the generic Agent core."""

from __future__ import annotations

from typing import Any


INTENT_PATTERNS = [
    (
        "operator_generation",
        [
            "operator를 만들",
            "operator 만들",
            "custom resource를 관리",
            "crd",
            "controller는",
            "spec에는",
            "status에는",
        ],
    ),
    ("log_analysis", ["로그", "오류 분석", "analysis", "failedstep", "stderr", "summary.json"]),
    ("recovery_planning", ["복구", "recovery", "수정 방향", "원인"]),
    ("e2e_validation", ["e2e", "kind", "클러스터", "배포 검증"]),
    ("scaffold_validation", ["make generate", "make manifests", "make test", "검증"]),
    ("operator_explanation", ["설명", "구조", "어떤 역할", "이해"]),
]


def analyze_requirement_intent(requirement_text: str) -> dict[str, Any]:
    text = requirement_text.lower()
    scores: list[dict[str, Any]] = []
    for intent, keywords in INTENT_PATTERNS:
        matched = [keyword for keyword in keywords if keyword.lower() in text]
        if matched:
            scores.append({"intent": intent, "score": len(matched), "matchedKeywords": matched})
    scores.sort(key=lambda item: item["score"], reverse=True)
    primary = scores[0]["intent"] if scores else "unknown_or_incomplete"
    managed_resources = infer_managed_resources(requirement_text)
    return {
        "primaryIntent": primary,
        "intentScores": scores,
        "managedResourceHints": managed_resources,
        "confidence": "high" if scores and scores[0]["score"] >= 2 else "medium" if scores else "low",
        "notes": [
            "The current requirement is the source of truth for planning.",
            "The Agent should ask for missing Operator details before executing mutating tools.",
        ],
    }


def infer_managed_resources(requirement_text: str) -> list[str]:
    from agent.tools.spec_generator import parse_controller

    controller = parse_controller(requirement_text, [])
    normalized = {"PVC": "PersistentVolumeClaim"}.get
    return sorted(
        {
            normalized(str(item), str(item))
            for item in controller.get("managedResources") or []
        }
    )
