#!/usr/bin/env python3
"""Requirement intent analysis and profile hinting for the generic Agent core."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


KNOWN_WORKLOADS = {
    "ConfigMap": ["configmap", "config map", "설정"],
    "Secret": ["secret", "비밀", "credential", "password"],
    "Deployment": ["deployment", "deploy", "배포"],
    "StatefulSet": ["statefulset", "stateful", "상태저장"],
    "Service": ["service", "svc", "서비스"],
    "Job": ["job", "batch", "학습", "training", "작업"],
    "CronJob": ["cronjob", "schedule", "스케줄"],
    "Pod": ["pod"],
    "PersistentVolumeClaim": ["persistentvolumeclaim", "pvc", "volume", "스토리지"],
}


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
            "Profile is treated as a hint, not as a fixed product template.",
            "The Agent should ask for missing Operator details before executing mutating tools.",
        ],
    }


def infer_managed_resources(requirement_text: str) -> list[str]:
    text = requirement_text.lower()
    resources = set()
    for resource, keywords in KNOWN_WORKLOADS.items():
        if resource.lower() in text or any(keyword.lower() in text for keyword in keywords):
            resources.add(resource)
    resources.update(re.findall(r"\b(ConfigMap|Secret|Deployment|StatefulSet|Service|Job|CronJob|Pod|PersistentVolumeClaim|PVC)\b", requirement_text))
    normalized = {"PVC": "PersistentVolumeClaim"}.get
    return sorted({normalized(item, item) for item in resources})


def select_profile_hint(
    requirement_text: str,
    explicit_profile_path: str | None,
    explicit_profile: dict[str, Any] | None,
    profiles_dir: Path | str = "profiles",
) -> dict[str, Any]:
    candidates = rank_profile_candidates(requirement_text, profiles_dir)
    if explicit_profile_path and explicit_profile:
        selected = summarize_profile(explicit_profile_path, explicit_profile)
        selected["selectionMode"] = "explicit-hint"
        selected["reason"] = "User provided this profile path; the Agent still plans from the requirement text."
        return {"selectedProfile": selected, "profileCandidates": candidates}
    if candidates and is_strong_profile_match(candidates[0], requirement_text):
        selected = dict(candidates[0])
        selected["selectionMode"] = "auto-hint"
        selected["reason"] = selected.get("reason") or "Best matching profile hint from managed resource overlap."
        return {"selectedProfile": selected, "profileCandidates": candidates}
    return {
        "selectedProfile": {
            "path": "",
            "name": "",
            "description": "",
            "managedResources": [],
            "selectionMode": "none",
            "reason": "No matching profile hint was found; generic Agent core still proceeds from requirement text.",
        },
        "profileCandidates": [],
    }


def is_strong_profile_match(candidate: dict[str, Any], requirement_text: str) -> bool:
    requirement_resources = set(infer_managed_resources(requirement_text))
    if not requirement_resources:
        return False
    matched = set(candidate.get("matchedResources") or [])
    coverage = len(matched) / max(len(requirement_resources), 1)
    return int(candidate.get("score", 0)) >= 5 and coverage >= 0.67


def rank_profile_candidates(requirement_text: str, profiles_dir: Path | str = "profiles") -> list[dict[str, Any]]:
    requirement_resources = set(infer_managed_resources(requirement_text))
    text = requirement_text.lower()
    candidates: list[dict[str, Any]] = []
    root = Path(profiles_dir)
    if not root.is_dir():
        return []
    for path in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        profile = summarize_profile(str(path), data)
        profile_resources = set(profile["managedResources"])
        overlap = sorted(requirement_resources & profile_resources)
        name = str(profile.get("name") or "").lower()
        description = str(profile.get("description") or "").lower()
        name_hits = 1 if name and name in text else 0
        description_hits = sum(1 for token in requirement_resources if token.lower() in description)
        score = len(overlap) * 3 + name_hits * 2 + description_hits
        if score <= 0:
            continue
        profile["score"] = score
        profile["matchedResources"] = overlap
        profile["reason"] = (
            "Matched managed resources: " + ", ".join(overlap)
            if overlap
            else "Matched profile name or description."
        )
        candidates.append(profile)
    candidates.sort(key=lambda item: item.get("score", 0), reverse=True)
    return candidates


def summarize_profile(path: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": path,
        "name": data.get("profileName", ""),
        "description": data.get("description", ""),
        "managedResources": data.get("managedResources") or [],
        "referencedResources": data.get("referencedResources") or [],
        "kindDeployment": data.get("kindDeployment") or {},
    }
