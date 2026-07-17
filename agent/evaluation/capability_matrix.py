#!/usr/bin/env python3
"""Derive capability support levels from compile and kind evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.tools.resource_catalog import load_resource_catalog


def build_capability_matrix(
    compile_results: dict[str, Any],
    kind_results: dict[str, Any],
) -> dict[str, Any]:
    if (
        compile_results.get("status") not in (None, "passed")
        or kind_results.get("status") not in (None, "passed")
    ):
        # 일부 또는 전체 lifecycle이 실행되지 않은 결과는 리소스 등급을
        # 낮추거나 올리는 근거로 사용할 수 없다. 진단 원본만 보존한다.
        return {
            "createdAt": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "status": "not-evaluated",
            "promotionEligible": False,
            "reason": (
                "compile and kind matrices must both pass before capability "
                "levels are evaluated"
            ),
            "capabilities": [],
            "counts": {
                "stable": 0,
                "beta": 0,
                "experimental": 0,
            },
        }
    compile_by_requirement = {
        str(item.get("requirement") or ""): item
        for item in compile_results.get("requirements") or []
    }
    catalog = load_resource_catalog()
    resources_by_name = catalog.by_name()
    observations: dict[str, list[dict[str, Any]]] = {
        item.kind: [] for item in catalog.resources
    }
    for case in kind_results.get("results") or []:
        if case.get("status") != "passed":
            # Failed or interrupted lifecycle runs are diagnostics, not
            # capability-grade evidence.
            continue
        requirement = str(case.get("requirement") or "")
        compiled = compile_by_requirement.get(requirement) or {}
        evidence = (
            (case.get("deploymentSummary") or {}).get("runtimeEvidence")
            or {}
        )
        for resource in compiled.get("managedResources") or []:
            raw_resource = str(resource)
            definition = resources_by_name.get(raw_resource)
            canonical = definition.kind if definition else raw_resource
            observations.setdefault(canonical, []).append(
                {
                    "requirement": requirement,
                    "compilePassed": bool(compiled.get("passed")),
                    "kindPassed": case.get("status") == "passed",
                    "runtimeEvidence": evidence,
                }
            )
    capabilities = []
    for resource, evidence in sorted(observations.items()):
        level = classify(evidence)
        capabilities.append(
            {
                "resource": resource,
                "level": level,
                "evidenceBased": True,
                "lastValidatedAt": datetime.now().astimezone().isoformat(
                    timespec="seconds"
                ),
                "evidence": evidence,
                "limitations": limitations(level, evidence),
            }
        )
    return {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "passed",
        "promotionEligible": True,
        "capabilities": capabilities,
        "counts": {
            level: sum(item["level"] == level for item in capabilities)
            for level in ("stable", "beta", "experimental")
        },
    }


def classify(observations: list[dict[str, Any]]) -> str:
    for item in observations:
        evidence = item.get("runtimeEvidence") or {}
        required = ("idempotency", "driftRecovery", "rbacLeastPrivilege", "deletionPolicy", "stateMachine")
        if item.get("kindPassed") and all(
            (evidence.get(name) or {}).get("status") == "passed"
            for name in required
        ):
            return "stable"
    if any(item.get("kindPassed") for item in observations):
        return "beta"
    return "experimental"


def limitations(level: str, observations: list[dict[str, Any]]) -> list[str]:
    if level == "stable":
        return []
    if not observations:
        return ["No kind lifecycle evidence is recorded."]
    missing = set()
    for item in observations:
        for name, value in (item.get("runtimeEvidence") or {}).items():
            if value.get("status") != "passed" and name != "finalizer":
                missing.add(name)
    return [f"Runtime evidence is incomplete: {name}" for name in sorted(missing)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile-results", required=True)
    parser.add_argument("--kind-results", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_capability_matrix(
        json.loads(Path(args.compile_results).read_text(encoding="utf-8")),
        json.loads(Path(args.kind_results).read_text(encoding="utf-8")),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
