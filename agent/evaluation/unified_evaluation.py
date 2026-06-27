#!/usr/bin/env python3
"""Combine regression evidence into one scored Agent evaluation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


SECTION_NAMES = (
    "requirementUnderstanding",
    "ragQuality",
    "artifactQuality",
    "validationSuccess",
    "safetyReliability",
    "e2eSuccess",
    "latency",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    root = Path(args.input_dir)
    output = (
        Path(args.output)
        if args.output
        else root / "final-evaluation.json"
    )
    payload = write_unified_evaluation(root, output)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["overallScore"] >= 70 else 1


def write_unified_evaluation(
    root: Path,
    output: Path | None = None,
) -> dict[str, Any]:
    payload = build_unified_evaluation(root)
    target = output or root / "final-evaluation.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


def build_unified_evaluation(root: Path) -> dict[str, Any]:
    profileless = read_json(root / "profileless" / "profileless-results.json")
    profileless_compile = read_json(
        root
        / "profileless-compile"
        / "profileless-compile-results.json"
    )
    rag = read_json(root / "rag-quality.json")
    reliability = read_json(
        root / "reliability" / "reliability-test-results.json"
    )
    kind_idempotency = read_json(
        root / "reliability" / "kind-idempotency-results.json"
    )
    profile_kind = read_json(
        root / "profile-kind" / "profile-kind-matrix.json"
    )
    profileless_kind = read_json(
        root
        / "profileless-kind"
        / "profileless-kind-results.json"
    )
    regression = read_json(root / "regression-summary.json")
    performance = read_json(root / "performance-trend.json")

    sections = {
        "requirementUnderstanding": requirement_section(profileless),
        "ragQuality": rag_section(rag),
        "artifactQuality": artifact_section(
            profileless_compile or profileless
        ),
        "validationSuccess": validation_section(
            regression,
            profileless_compile or profileless,
        ),
        "safetyReliability": reliability_section(reliability),
        "e2eSuccess": e2e_section(
            profile_kind,
            kind_idempotency,
            profileless_kind,
        ),
        "latency": latency_section(performance),
    }
    section_scores = [
        float(sections[name]["score"])
        for name in SECTION_NAMES
    ]
    overall = round(sum(section_scores) / len(section_scores), 1)
    return {**sections, "overallScore": overall}


def requirement_section(data: dict[str, Any]) -> dict[str, Any]:
    items = data.get("requirements") or []
    if not items:
        return not_run("profileless requirement results are unavailable")
    passed = sum(1 for item in items if item.get("passed"))
    return scored(
        passed,
        len(items),
        requirements=len(items),
        kinds=[item.get("kind") for item in items],
        profileModes=[
            item.get("profileSelectionMode") for item in items
        ],
        profileHintsDisabled=bool(
            data.get("profileHintsDisabled")
        ),
    )


def rag_section(data: dict[str, Any]) -> dict[str, Any]:
    metrics = data.get("metrics") or {}
    if not metrics:
        return not_run("RAG quality results are unavailable")
    hit_at_3 = float(metrics.get("hitAt3") or 0)
    return {
        "status": data.get("status") or "failed",
        "score": round(hit_at_3 * 100, 1),
        "metrics": metrics,
        "thresholds": data.get("thresholds") or {},
    }


def artifact_section(data: dict[str, Any]) -> dict[str, Any]:
    qualities = [
        item.get("controllerQuality") or {}
        for item in data.get("requirements") or []
    ]
    measured = [
        item for item in qualities if item.get("status") != "not-run"
    ]
    if not measured:
        return not_run("Controller artifacts were not generated")
    score = round(
        sum(float(item.get("score") or 0) for item in measured)
        / len(measured),
        1,
    )
    return {
        "status": "passed" if all(
            item.get("status") == "passed" for item in measured
        ) else "failed",
        "score": score,
        "evaluatedControllers": len(measured),
        "criteria": list(
            (measured[0].get("criteria") or {}).keys()
        ),
    }


def validation_section(
    regression: dict[str, Any],
    profileless: dict[str, Any],
) -> dict[str, Any]:
    checks = regression.get("checks") or []
    validation_checks = [
        item
        for item in checks
        if item.get("name")
        in {
            "agent-unit-tests",
            "llm-unit-tests",
            "tool-unit-tests",
            "evaluation-unit-tests",
            "web-unit-tests",
        }
    ]
    artifact_tests = []
    for item in profileless.get("requirements") or []:
        quality = item.get("controllerQuality") or {}
        test_result = (quality.get("criteria") or {}).get("testsPassed")
        if test_result:
            artifact_tests.append(
                {"exitCode": 0 if test_result.get("passed") else 1}
            )
    combined = [*validation_checks, *artifact_tests]
    if not combined:
        return not_run("Validation results are unavailable")
    passed = sum(1 for item in combined if item.get("exitCode") == 0)
    return scored(passed, len(combined), checks=len(combined))


def reliability_section(data: dict[str, Any]) -> dict[str, Any]:
    tests = data.get("tests") or []
    if not tests:
        return not_run("Reliability results are unavailable")
    passed = sum(1 for item in tests if item.get("passed"))
    return scored(
        passed,
        len(tests),
        passedTests=passed,
        failedTests=len(tests) - passed,
    )


def e2e_section(
    profile_kind: dict[str, Any],
    idempotency: dict[str, Any],
    profileless_kind: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence: list[bool] = []
    profile_results = [
        item
        for item in profile_kind.get("results") or []
        if item.get("status") != "skipped"
    ]
    evidence.extend(item.get("status") == "passed" for item in profile_results)
    lifecycle_checks = []
    for item in profile_results:
        checks = (
            (item.get("deploymentSummary") or {}).get("checks") or {}
        )
        lifecycle = [
            bool((checks.get("lifecycleIdempotency") or {}).get(
                "reapplyStable"
            )),
            all(
                assertion.get("passed")
                for assertion in (
                    (checks.get("lifecycleUpdate") or {}).get(
                        "assertions"
                    )
                    or []
                )
            )
            if checks.get("lifecycleUpdate")
            else True,
            all(
                result.get("passed")
                for result in (
                    (checks.get("lifecycleDelete") or {}).get(
                        "managedResources"
                    )
                    or {}
                ).values()
            )
            if checks.get("lifecycleDelete")
            else False,
            bool((checks.get("lifecycleRestore") or {}).get("restored")),
        ]
        if checks:
            lifecycle_checks.extend(lifecycle)
    evidence.extend(lifecycle_checks)
    if (
        idempotency
        and not idempotency.get("skipped")
        and idempotency.get("status") != "skipped"
    ):
        evidence.extend(
            [
                bool(idempotency.get("reapplyIdempotent")),
                bool(idempotency.get("specChangeIdempotent")),
            ]
        )
    profileless_runs = 0
    if profileless_kind:
        profileless_results = (
            profileless_kind.get("results")
            or [profileless_kind]
        )
        profileless_runs = len(profileless_results)
        for item in profileless_results:
            evidence.append(
                item.get("status") == "passed"
                and item.get("profileUsed") is False
            )
            checks = (
                (item.get("deploymentSummary") or {}).get("checks")
                or {}
            )
            profileless_lifecycle = lifecycle_evidence(checks)
            evidence.extend(profileless_lifecycle)
            lifecycle_checks.extend(profileless_lifecycle)
    if not evidence:
        return not_run("kind E2E results are unavailable")
    return scored(
        sum(1 for item in evidence if item),
        len(evidence),
        profileRuns=len(profile_results),
        profilelessKindRuns=profileless_runs,
        lifecycleChecks=len(lifecycle_checks),
    )


def lifecycle_evidence(checks: dict[str, Any]) -> list[bool]:
    if not checks:
        return [False, False, False, False]
    update = checks.get("lifecycleUpdate") or {}
    assertions = update.get("assertions") or []
    deleted = (
        (checks.get("lifecycleDelete") or {}).get("managedResources")
        or {}
    )
    evidence = [
        bool(
            (checks.get("lifecycleIdempotency") or {}).get(
                "reapplyStable"
            )
        ),
        (
            all(item.get("passed") for item in assertions)
            if update
            else True
        ),
        bool(deleted)
        and all(item.get("passed") for item in deleted.values()),
        bool((checks.get("lifecycleRestore") or {}).get("restored")),
    ]
    registration = checks.get("finalizerRegistration") or {}
    lifecycle = checks.get("finalizerLifecycle") or {}
    if registration or lifecycle:
        evidence.extend(
            [
                bool(registration.get("registered")),
                bool(lifecycle.get("customResourceRemoved")),
                bool(lifecycle.get("explicitResourcesRemoved")),
            ]
        )
    return evidence


def latency_section(data: dict[str, Any]) -> dict[str, Any]:
    current = data.get("current") or {}
    if not current:
        return not_run("Performance trend is unavailable")
    total = float(current.get("totalSeconds") or 0)
    suite = str(current.get("suite") or "quick")
    target = {"quick": 30.0, "standard": 180.0, "full": 1200.0}.get(
        suite,
        180.0,
    )
    score = 100.0 if total <= target else max(
        0.0,
        round(target / total * 100, 1),
    )
    return {
        "status": "passed" if total <= target else "failed",
        "score": score,
        "suite": suite,
        "totalSeconds": total,
        "targetSeconds": target,
        "checks": current.get("checks") or {},
    }


def scored(passed: int, total: int, **details: Any) -> dict[str, Any]:
    score = round(passed / total * 100, 1) if total else 0.0
    return {
        "status": "passed" if passed == total and total else "failed",
        "score": score,
        "passed": passed,
        "total": total,
        **details,
    }


def not_run(reason: str) -> dict[str, Any]:
    return {"status": "not-run", "score": 0.0, "reason": reason}


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
