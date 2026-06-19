"""Normalize retrieval output and select purpose-specific Agent context."""

from __future__ import annotations

import json
import os
from typing import Any

from agent.rag.retriever import search_detailed as retrieve_knowledge_detailed


def perform_retrieval(
    query: str,
    limit: int = 3,
    purpose: str = "requirement",
) -> dict[str, Any]:
    details = retrieve_knowledge_detailed(query, limit=limit)
    selected = select_context(details, limit, purpose)
    return {
        "retrievalQuery": {"query": query},
        "retrievalMode": details.get("retrievalMode", ""),
        "vectorSearchResults": details.get("vectorSearchResults") or [],
        "keywordSearchResults": details.get("keywordSearchResults") or [],
        "hybridResults": details.get("hybridResults") or [],
        "rerankedResults": details.get("rerankedResults") or [],
        "selectedContext": selected[:limit],
        "fallbackUsed": bool(details.get("fallbackUsed")),
        "fallbackReason": details.get("fallbackReason", ""),
        "embeddingModel": details.get("embeddingModel", ""),
        "embeddingDimension": details.get("embeddingDimension"),
        "rerankerModel": details.get("rerankerModel", ""),
        "elapsedSeconds": details.get("elapsedSeconds"),
        "rerankerOutput": details.get("rerankerOutput") or {},
    }


def select_context(
    details: dict[str, Any],
    limit: int,
    purpose: str,
) -> list[dict[str, Any]]:
    pool = (
        details.get("rerankedResults")
        or details.get("selectedContext")
        or details.get("hybridResults")
        or []
    )
    selected: list[dict[str, Any]] = []
    used_sources: set[str] = set()

    def add_matching(
        categories: set[str],
        max_count: int,
        context_type: str,
    ) -> None:
        count = 0
        for item in pool:
            if count >= max_count or len(selected) >= limit:
                return
            source = str(item.get("sourcePath") or item.get("path") or "")
            if not source or source in used_sources:
                continue
            if str(item.get("category") or "") not in categories:
                continue
            row = dict(item)
            row["contextType"] = context_type
            row["reason"] = row.get("reason") or (
                f"Selected for {purpose} context from {row.get('category')} document."
            )
            selected.append(row)
            used_sources.add(source)
            count += 1

    if purpose == "requirement":
        add_matching({"guide", "troubleshooting"}, 2, "reference")
        add_matching({"example", "few-shot"}, 1, "few-shot")
    elif purpose in {"recovery", "log-analysis"}:
        add_matching({"troubleshooting", "guide"}, 2, "reference")
        add_matching({"few-shot", "example"}, 1, "few-shot")

    for item in pool:
        if len(selected) >= limit:
            break
        source = str(item.get("sourcePath") or item.get("path") or "")
        if not source or source in used_sources:
            continue
        row = dict(item)
        row["contextType"] = row.get("contextType") or (
            "few-shot"
            if row.get("category") in {"example", "few-shot"}
            else "reference"
        )
        row["reason"] = row.get("reason") or (
            f"Selected as fallback context for {purpose}."
        )
        selected.append(row)
        used_sources.add(source)
    return selected[:limit]


def requirement_rag_limit() -> int:
    raw = os.environ.get("AGENT_REQUIREMENT_RAG_LIMIT", "2")
    try:
        return max(1, min(3, int(raw)))
    except ValueError:
        return 2


def build_log_rag_query(
    summary: dict[str, Any],
    analysis_text: str,
) -> str:
    return "\n".join(
        [
            "Kubebuilder Operator troubleshooting log analysis",
            str(summary.get("failedStep") or "succeeded"),
            " ".join(str(item) for item in summary.get("warnings") or []),
            json.dumps(summary.get("jobSpecValidation") or {}, ensure_ascii=False),
            analysis_text[:2000],
        ]
    )
