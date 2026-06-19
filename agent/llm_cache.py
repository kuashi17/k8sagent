"""Persistent cache helpers for Agent LLM planning."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.llm.client import config_from_env


AGENT_CACHE_ROOT = Path(".cache") / "agent"
REQUIREMENT_PLAN_CACHE_VERSION = "requirement-planning-v4"


def requirement_plan_cache_metadata(llm_input: dict[str, Any]) -> dict[str, Any]:
    cfg = config_from_env(purpose="planning")
    payload = {
        "version": REQUIREMENT_PLAN_CACHE_VERSION,
        "localLLM": {"baseUrl": cfg.base_url, "model": cfg.model},
        "llmInput": llm_input,
    }
    key = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    path = AGENT_CACHE_ROOT / "llm-plans" / f"{key}.json"
    return {"key": key, "path": path}


def read_requirement_plan_cache(
    cache: dict[str, Any],
    fallback_input: dict[str, Any],
) -> dict[str, Any] | None:
    path = Path(cache["path"])
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "llmInput": data.get("llmInput") or fallback_input,
        "llmOutput": data.get("llmOutput") or {},
        "rawOutput": data.get("rawOutput") or "",
        "createdAt": data.get("createdAt", ""),
    }


def write_requirement_plan_cache(
    path: Path,
    llm_input: dict[str, Any],
    output: dict[str, Any],
    raw: str,
    local_llm: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cacheVersion": REQUIREMENT_PLAN_CACHE_VERSION,
        "localLLM": local_llm,
        "llmInput": llm_input,
        "llmOutput": output,
        "rawOutput": raw,
    }
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
