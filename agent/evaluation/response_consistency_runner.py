#!/usr/bin/env python3
"""Measure semantic accuracy and repeatability of requirement interpretation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.context_builder import missing_information, summarize_requirement
from agent.error_registry import ErrorCode
from agent.tools.spec_generator import generate_spec


DEFAULT_MATRIX = REPO_ROOT / "evaluation" / "fixtures" / "response-consistency-matrix.yaml"


def canonical_contract(text: str, source: Path) -> dict[str, Any]:
    spec = generate_spec(text, source)
    summary = summarize_requirement(text)
    rbac = {
        str(item.get("resource")): sorted(str(verb) for verb in item.get("verbs") or [])
        for item in (spec.get("rbac") or {}).get("resources") or []
    }
    errors = [str(item) for item in spec.get("errors") or []]
    ambiguous_types = list(summary.get("ambiguousFieldTypes") or [])
    error_code = ""
    if ambiguous_types:
        error_code = ErrorCode.INVALID_FIELD_TYPE.value
    elif errors:
        error_code = (
            ErrorCode.INVALID_FIELD_TYPE.value
            if any("type" in item.lower() for item in errors)
            else ErrorCode.REQUIRED_INPUT_MISSING.value
        )
    return {
        "api": spec.get("api") or {},
        "specFields": {
            str(item.get("name")): str(item.get("type"))
            for item in spec.get("specFields") or []
        },
        "statusFields": {
            str(item.get("name")): str(item.get("type"))
            for item in spec.get("statusFields") or []
        },
        "managedResources": list((spec.get("controller") or {}).get("managedResources") or []),
        "observedResources": list((spec.get("controller") or {}).get("observedResources") or []),
        "resourcePolicies": [
            {
                output_key: item.get(source_key)
                for output_key, source_key in (
                    ("resource", "kind"),
                    ("strategy", "strategy"),
                    ("ownership", "ownership"),
                    ("deletionPolicy", "deletionPolicy"),
                )
            }
            for item in (spec.get("controller") or {}).get("resourcePolicies") or []
        ],
        "rbac": rbac,
        "missingInformation": missing_information(summary, text),
        "ambiguousFieldTypes": ambiguous_types,
        "errorCode": error_code,
    }


def compare_expected(actual: dict[str, Any], expected: dict[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for key, value in expected.items():
        if key == "forbiddenResources":
            present = sorted(
                set(actual.get("managedResources") or [])
                | set(actual.get("observedResources") or [])
            )
            forbidden = sorted(set(present) & set(value))
            if forbidden:
                failures.append(
                    {
                        "field": "forbiddenResources",
                        "expected": [],
                        "actual": forbidden,
                    }
                )
            continue
        if key == "forbiddenRbac":
            for resource, verbs in value.items():
                present = sorted(set(actual["rbac"].get(resource, [])) & set(verbs))
                if present:
                    failures.append({"field": f"forbiddenRbac.{resource}", "expected": [], "actual": present})
            continue
        if key == "rbac":
            for resource, verbs in value.items():
                actual_verbs = actual["rbac"].get(resource, [])
                if sorted(actual_verbs) != sorted(verbs):
                    failures.append({"field": f"rbac.{resource}", "expected": sorted(verbs), "actual": sorted(actual_verbs)})
            continue
        if actual.get(key) != value:
            failures.append({"field": key, "expected": value, "actual": actual.get(key)})
    return failures


def fingerprint(contract: dict[str, Any]) -> str:
    encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def evaluate_case(case: dict[str, Any], runs: int, matrix_path: Path) -> dict[str, Any]:
    started = time.monotonic()
    contracts = [canonical_contract(str(case["requirement"]), matrix_path) for _ in range(runs)]
    fingerprints = [fingerprint(item) for item in contracts]
    failures = compare_expected(contracts[0], case.get("expected") or {})
    return {
        "id": case["id"],
        "status": "passed" if not failures and len(set(fingerprints)) == 1 else "failed",
        "accuracyPassed": not failures,
        "consistencyPassed": len(set(fingerprints)) == 1,
        "runs": runs,
        "uniqueFingerprints": len(set(fingerprints)),
        "fingerprint": fingerprints[0],
        "failures": failures,
        "contract": contracts[0],
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }


def run_matrix(matrix_path: Path, runs: int) -> dict[str, Any]:
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8")) or {}
    cases = matrix.get("cases") or []
    case_ids = [str(case.get("id") or "") for case in cases]
    if not cases or any(not item for item in case_ids) or len(set(case_ids)) != len(case_ids):
        raise ValueError("matrix cases require unique non-empty ids")
    if any(not case.get("requirement") or not case.get("expected") for case in cases):
        raise ValueError("every matrix case requires requirement and expected contracts")
    results = [evaluate_case(case, runs, matrix_path) for case in cases]
    result_by_id = {item["id"]: item for item in results}
    equivalence_groups = []
    for group in matrix.get("equivalenceGroups") or []:
        members = [str(item) for item in group.get("cases") or []]
        unknown = [item for item in members if item not in result_by_id]
        if unknown or len(members) < 2:
            raise ValueError(f"invalid equivalence group {group.get('id')}: {unknown}")
        fingerprints = {result_by_id[item]["fingerprint"] for item in members}
        equivalence_groups.append(
            {
                "id": group["id"],
                "cases": members,
                "status": "passed" if len(fingerprints) == 1 else "failed",
                "uniqueFingerprints": len(fingerprints),
            }
        )
    accurate = sum(item["accuracyPassed"] for item in results)
    passed = sum(item["status"] == "passed" for item in results)
    groups_passed = all(item["status"] == "passed" for item in equivalence_groups)
    return {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "passed" if passed == len(results) and results and groups_passed else "failed",
        "runsPerCase": runs,
        "summary": {
            "cases": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "accuracyRate": round(accurate / len(results), 4) if results else 0,
            "consistentCases": sum(item["consistencyPassed"] for item in results),
            "equivalentGroups": sum(item["status"] == "passed" for item in equivalence_groups),
            "equivalenceGroupCount": len(equivalence_groups),
        },
        "equivalenceGroups": equivalence_groups,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", default=str(DEFAULT_MATRIX))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--output", default="evaluation/results/response-consistency.json")
    args = parser.parse_args()
    if args.runs < 2:
        parser.error("--runs must be at least 2")
    result = run_matrix(Path(args.matrix), args.runs)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], **result["summary"], "output": str(output)}, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
