"""Persistent cache helpers for Agent LLM planning."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.llm.client import config_from_env
from agent.contracts import RequirementPlan
from agent.llm.prompts import (
    REQUIREMENT_PLANNER_PROMPT,
    REQUIREMENT_PLAN_REPAIR_PROMPT,
    SYSTEM_PROMPT,
)


AGENT_CACHE_ROOT = Path(".cache") / "agent"
REQUIREMENT_PLAN_CACHE_VERSION = "requirement-planning-v5"


def requirement_plan_cache_metadata(llm_input: dict[str, Any]) -> dict[str, Any]:
    cfg = config_from_env(purpose="planning")
    contract = planning_cache_contract()
    payload = {
        "version": REQUIREMENT_PLAN_CACHE_VERSION,
        "contractDigest": contract["digest"],
        "localLLM": {"baseUrl": cfg.base_url, "model": cfg.model},
        "llmInput": llm_input,
    }
    key = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    path = AGENT_CACHE_ROOT / "llm-plans" / f"{key}.json"
    return {
        "key": key,
        "path": path,
        "cacheVersion": REQUIREMENT_PLAN_CACHE_VERSION,
        "contractDigest": contract["digest"],
        "contractComponents": contract["components"],
    }


def read_requirement_plan_cache(
    cache: dict[str, Any],
    fallback_input: dict[str, Any],
) -> dict[str, Any] | None:
    path = Path(cache["path"])
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("cacheVersion") != REQUIREMENT_PLAN_CACHE_VERSION:
        return None
    if data.get("contractDigest") != cache.get("contractDigest"):
        return None
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
    contract = planning_cache_contract()
    data = {
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "cacheVersion": REQUIREMENT_PLAN_CACHE_VERSION,
        "contractDigest": contract["digest"],
        "contractComponents": contract["components"],
        "localLLM": local_llm,
        "llmInput": llm_input,
        "llmOutput": output,
        "rawOutput": raw,
    }
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def planning_cache_contract() -> dict[str, Any]:
    components = {
        "prompt": digest_json(
            {
                "system": SYSTEM_PROMPT,
                "planning": REQUIREMENT_PLANNER_PROMPT,
                "repair": REQUIREMENT_PLAN_REPAIR_PROMPT,
            }
        ),
        "schema": digest_json(RequirementPlan.model_json_schema()),
        "tools": digest_tool_contract(),
    }
    return {
        "digest": digest_json(components),
        "components": components,
    }


def digest_tool_contract() -> str:
    root = Path(__file__).resolve().parent
    payload = {
        name: (root / name).read_text(encoding="utf-8")
        for name in ("execution_engine.py", "tool_validator.py")
    }
    return digest_json(payload)


def digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
