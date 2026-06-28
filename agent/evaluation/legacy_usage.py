#!/usr/bin/env python3
"""Inventory deprecated code paths and reject unapproved new references."""

from __future__ import annotations

import argparse
import fnmatch
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = REPO_ROOT / "config" / "legacy-path-policy.yaml"
SCAN_SUFFIXES = {".py", ".yaml", ".yml"}
EXCLUDED_PARTS = {".git", ".tools", "evaluation", "logs", "workspace"}


def measure_legacy_usage(
    root: Path,
    policy_path: Path,
) -> dict[str, Any]:
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8")) or {}
    entries = []
    violations = []
    files = [
        path
        for path in scan_files(root)
        if path.resolve() != policy_path.resolve()
    ]
    for configured in policy.get("paths") or []:
        item = dict(configured)
        allowed = [str(value) for value in item.get("allowedPaths") or []]
        references = []
        for path in files:
            relative = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in item.get("patterns") or []:
                count = text.count(str(pattern))
                if not count:
                    continue
                approved = any(fnmatch.fnmatch(relative, rule) for rule in allowed)
                reference = {
                    "path": relative,
                    "pattern": str(pattern),
                    "count": count,
                    "approved": approved,
                }
                references.append(reference)
                if not approved:
                    violations.append({"legacyPath": item.get("id"), **reference})
        entries.append(
            {
                "id": str(item.get("id") or ""),
                "status": str(item.get("status") or "deprecated"),
                "rationale": str(item.get("rationale") or ""),
                "removalCondition": str(item.get("removalCondition") or ""),
                "referenceCount": sum(ref["count"] for ref in references),
                "maxReferences": item.get("maxReferences"),
                "targetReferences": item.get("targetReferences", 0),
                "references": references,
            }
        )
        reference_count = sum(ref["count"] for ref in references)
        maximum = item.get("maxReferences")
        if maximum is not None and reference_count > int(maximum):
            violations.append(
                {
                    "legacyPath": item.get("id"),
                    "reason": "reference-budget-exceeded",
                    "referenceCount": reference_count,
                    "maxReferences": int(maximum),
                }
            )
    return {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "passed" if not violations else "failed",
        "policy": str(policy_path),
        "entries": entries,
        "violations": violations,
    }


def scan_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in SCAN_SUFFIXES
        and not EXCLUDED_PARTS.intersection(path.relative_to(root).parts)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if not output.is_absolute():
        output = REPO_ROOT / output
    result = measure_legacy_usage(REPO_ROOT, Path(args.policy))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
