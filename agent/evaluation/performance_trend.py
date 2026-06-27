"""Persist regression timing evidence across local and CI runs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def write_performance_trend(
    output_dir: Path,
    summary: dict[str, Any],
    history_file: Path | None = None,
) -> dict[str, Any]:
    current = {
        "createdAt": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "suite": summary["suite"],
        "status": summary["status"],
        "checks": {
            item["name"]: item["elapsedSeconds"]
            for item in summary["checks"]
        },
        "totalSeconds": round(
            sum(
                float(item["elapsedSeconds"])
                for item in summary["checks"]
            ),
            3,
        ),
    }
    previous = read_history(history_file)
    if not previous:
        previous = find_previous_performance(output_dir)
    payload = {"current": current, "previous": previous}
    write_json(output_dir / "performance-trend.json", payload)
    if history_file:
        write_json(history_file, current)
    return payload


def read_history(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    data = read_json(path)
    return data.get("current") or data


def find_previous_performance(output_dir: Path) -> dict[str, Any]:
    candidates = sorted(
        (
            path
            for path in output_dir.parent.glob(
                "*/performance-trend.json"
            )
            if path.parent != output_dir
        ),
        reverse=True,
    )
    for path in candidates:
        data = read_json(path)
        if data:
            return data.get("current") or {}
    return {}


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
