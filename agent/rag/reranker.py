#!/usr/bin/env python3
"""Local LLM reranker for hybrid RAG results."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llm.client import LLMUnavailable, chat_json, config_from_env
from agent.llm.planner import LLMOutputParseError, parse_json_object


RERANKER_SYSTEM_PROMPT = """\
You are a local RAG reranker for a Kubebuilder Operator Agent.
Score each candidate chunk from 0 to 100 for relevance to the query.
Return JSON only. Do not include Markdown.
"""


RERANKER_PROMPT = """\
Rank the candidate chunks for the query.

Required JSON shape:
{{
  "rankedResults": [
    {{
      "chunkId": "...",
      "rerankScore": 0,
      "reason": "short reason"
    }}
  ]
}}

Rules:
- Score higher when the chunk directly answers the query.
- Prefer troubleshooting documents for error queries.
- Prefer example documents for domain-specific Operator examples.
- Do not invent chunkIds.
- Return JSON only.

Query:
{query}

Candidates:
{candidates}
"""


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    final_top_n: int = 3,
    max_candidates: int = 6,
    content_limit: int = 700,
) -> dict[str, Any]:
    started = time.time()
    limited = candidates[:max_candidates]
    compact_candidates = [
        {
            "chunkId": item.get("chunkId"),
            "sourcePath": item.get("sourcePath") or item.get("path"),
            "title": item.get("title"),
            "category": item.get("category"),
            "combinedScore": item.get("combinedScore"),
            "content": str(item.get("content") or item.get("excerpt") or "")[:content_limit],
        }
        for item in limited
    ]
    fallback = False
    raw = ""
    parsed: dict[str, Any] = {}
    try:
        raw = call_chat_json_with_hard_timeout(
            RERANKER_SYSTEM_PROMPT,
            RERANKER_PROMPT.format(query=query, candidates=json.dumps(compact_candidates, indent=2, ensure_ascii=False)),
        )
        parsed = parse_json_object(raw)
        ranked = normalize_reranker_output(parsed, limited)
    except (LLMUnavailable, LLMOutputParseError, Exception) as exc:  # noqa: BLE001
        fallback = True
        raw = str(getattr(exc, "raw_output", "") or exc)
        ranked = fallback_ranking(limited)

    return {
        "query": query,
        "rerankerModel": config_from_env().model,
        "fallbackUsed": fallback,
        "fallbackReason": raw if fallback else "",
        "rawOutput": raw,
        "rankedResults": ranked[:final_top_n],
        "allRankedResults": ranked,
        "elapsedSeconds": round(time.time() - started, 3),
    }


def call_chat_json_with_hard_timeout(system_prompt: str, user_prompt: str) -> str:
    timeout_seconds = int(os.environ.get("LOCAL_LLM_TIMEOUT_SECONDS", "180"))
    if timeout_seconds <= 0:
        return chat_json(system_prompt, user_prompt)

    queue: mp.Queue = mp.Queue(maxsize=1)
    process = mp.Process(target=chat_worker, args=(system_prompt, user_prompt, queue), daemon=True)
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(2)
        raise TimeoutError(f"reranker timed out after {timeout_seconds} seconds")
    if queue.empty():
        raise RuntimeError("reranker worker exited without output")
    payload = queue.get()
    if payload.get("ok"):
        return str(payload.get("value") or "")
    raise RuntimeError(str(payload.get("error") or "reranker worker failed"))


def chat_worker(system_prompt: str, user_prompt: str, queue: Any) -> None:
    try:
        queue.put({"ok": True, "value": chat_json(system_prompt, user_prompt)})
    except Exception as exc:  # noqa: BLE001
        queue.put({"ok": False, "error": str(exc)})


def normalize_reranker_output(parsed: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(item.get("chunkId")): item for item in candidates}
    ranked = []
    seen: set[str] = set()
    for item in parsed.get("rankedResults") or []:
        if not isinstance(item, dict):
            continue
        chunk_id = str(item.get("chunkId") or "")
        if chunk_id not in by_id or chunk_id in seen:
            continue
        seen.add(chunk_id)
        base = dict(by_id[chunk_id])
        base["rerankScore"] = safe_int(item.get("rerankScore"), 0)
        base["reason"] = str(item.get("reason") or "")
        ranked.append(base)
    for item in fallback_ranking([candidate for candidate in candidates if str(candidate.get("chunkId")) not in seen]):
        ranked.append(item)
    ranked.sort(key=lambda row: (-safe_int(row.get("rerankScore"), 0), -float(row.get("combinedScore") or 0.0)))
    return ranked


def fallback_ranking(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for item in sorted(candidates, key=lambda row: -float(row.get("combinedScore") or row.get("vectorScore") or row.get("score") or 0.0)):
        base = dict(item)
        base["rerankScore"] = int(round(float(base.get("combinedScore") or 0.0) * 100))
        base["reason"] = "Fallback ranking by combined score."
        ranked.append(base)
    return ranked


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
