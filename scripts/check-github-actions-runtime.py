#!/usr/bin/env python3
"""Reject official GitHub Actions versions that still use Node.js 20."""

from __future__ import annotations

import re
from pathlib import Path


WORKFLOW_DIR = Path(".github/workflows")
ACTION_PATTERN = re.compile(
    r"uses:\s*actions/(checkout|setup-python|cache(?:/restore|/save)?|upload-artifact)@v(\d+)"
)
MINIMUM_MAJOR = {
    "checkout": 5,
    "setup-python": 6,
    "cache": 5,
    "cache/restore": 5,
    "cache/save": 5,
    "upload-artifact": 6,
}


def main() -> int:
    violations: list[str] = []
    checked = 0
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            match = ACTION_PATTERN.search(line)
            if not match:
                continue
            checked += 1
            action, major_text = match.groups()
            major = int(major_text)
            if major < MINIMUM_MAJOR[action]:
                violations.append(
                    f"{path}:{line_number}: actions/{action}@v{major} "
                    "does not meet the Node.js 24 runtime baseline"
                )
    if violations:
        print("\n".join(violations))
        return 1
    if checked == 0:
        print("No monitored official GitHub Actions were found.")
        return 1
    print(f"GitHub Actions Node.js 24 baseline passed ({checked} uses).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
