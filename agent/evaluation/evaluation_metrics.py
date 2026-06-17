#!/usr/bin/env python3
"""Metric helpers for RAG evaluation runs."""

from __future__ import annotations

import math
from statistics import mean
from typing import Any


def normalize_source_path(value: str) -> str:
    normalized = str(value or "").replace("\\", "/")
    if "#chunk-" in normalized:
        normalized = normalized.split("#chunk-", 1)[0]
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def retrieved_source(item: dict[str, Any]) -> str:
    return normalize_source_path(item.get("sourcePath") or item.get("path") or item.get("chunkId") or "")


def first_relevant_rank(retrieved: list[dict[str, Any]], expected_sources: list[str]) -> int | None:
    expected = {normalize_source_path(source) for source in expected_sources}
    for index, item in enumerate(retrieved, start=1):
        if retrieved_source(item) in expected:
            return index
    return None


def recall_at_k(retrieved: list[dict[str, Any]], expected_sources: list[str], k: int) -> float:
    expected = {normalize_source_path(source) for source in expected_sources}
    if not expected:
        return 0.0
    seen = {retrieved_source(item) for item in retrieved[:k]}
    return len(expected & seen) / len(expected)


def hit_at_k(rank: int | None, k: int) -> bool:
    return bool(rank and rank <= k)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * p
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def compute_mode_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    if not total:
        return {
            "queryCount": 0,
            "hitAt1": 0.0,
            "hitAt3": 0.0,
            "recallAt3": 0.0,
            "recallAt5": 0.0,
            "mrr": 0.0,
            "avgLatencySeconds": 0.0,
            "p95LatencySeconds": 0.0,
            "fallbackCount": 0,
            "rerankerTimeoutCount": 0,
        }

    ranks = [item.get("firstRelevantRank") for item in results]
    latencies = [float(item.get("elapsedSeconds") or 0.0) for item in results]
    return {
        "queryCount": total,
        "hitAt1": round(sum(1 for rank in ranks if hit_at_k(rank, 1)) / total, 4),
        "hitAt3": round(sum(1 for rank in ranks if hit_at_k(rank, 3)) / total, 4),
        "recallAt3": round(mean(float(item.get("recallAt3") or 0.0) for item in results), 4),
        "recallAt5": round(mean(float(item.get("recallAt5") or 0.0) for item in results), 4),
        "mrr": round(mean((1 / rank) if rank else 0.0 for rank in ranks), 4),
        "avgLatencySeconds": round(mean(latencies), 4),
        "p95LatencySeconds": round(percentile(latencies, 0.95), 4),
        "fallbackCount": sum(1 for item in results if item.get("fallbackUsed")),
        "rerankerTimeoutCount": sum(1 for item in results if item.get("rerankerTimeout")),
    }


def summarize_query_result(
    query_item: dict[str, Any],
    retrieval_response: dict[str, Any],
    elapsed_seconds: float,
) -> dict[str, Any]:
    expected = query_item.get("expectedSources") or []
    retrieved = retrieval_response.get("selectedContext") or []
    rank = first_relevant_rank(retrieved, expected)
    fallback_reason = str(retrieval_response.get("fallbackReason") or "")
    reranker_output = retrieval_response.get("rerankerOutput") or {}
    reranker_error = str(reranker_output.get("error") or reranker_output.get("fallbackReason") or fallback_reason)
    reranker_timeout = "timeout" in reranker_error.lower() or "timed out" in reranker_error.lower()
    return {
        "id": query_item.get("id"),
        "category": query_item.get("category"),
        "query": query_item.get("query"),
        "expectedSources": expected,
        "expectedKeywords": query_item.get("expectedKeywords") or [],
        "retrievedSources": [retrieved_source(item) for item in retrieved],
        "retrieved": [
            {
                "sourcePath": retrieved_source(item),
                "title": item.get("title") or "",
                "category": item.get("category") or "",
                "score": item.get("rerankScore", item.get("combinedScore", item.get("vectorScore", item.get("score")))),
            }
            for item in retrieved
        ],
        "firstRelevantRank": rank,
        "hitAt1": hit_at_k(rank, 1),
        "hitAt3": hit_at_k(rank, 3),
        "recallAt3": round(recall_at_k(retrieved, expected, 3), 4),
        "recallAt5": round(recall_at_k(retrieved, expected, 5), 4),
        "elapsedSeconds": round(elapsed_seconds, 4),
        "fallbackUsed": bool(retrieval_response.get("fallbackUsed")),
        "fallbackReason": fallback_reason,
        "rerankerTimeout": reranker_timeout,
        "success": bool(rank),
    }
