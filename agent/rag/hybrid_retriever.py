#!/usr/bin/env python3
"""Hybrid vector + keyword retriever for local knowledge-base RAG."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.rag import vector_store
from agent.rag.reranker import rerank


DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_KEYWORD_WEIGHT = 0.3


def hybrid_search(
    query: str,
    keyword_results: list[dict[str, Any]],
    knowledge_base: str | Path = vector_store.DEFAULT_KNOWLEDGE_BASE,
    index_dir: str | Path = vector_store.DEFAULT_INDEX_DIR,
    vector_top_k: int = 8,
    keyword_top_k: int = 5,
    final_top_n: int = 3,
    rerank_enabled: bool = True,
    allow_keyword_fallback: bool = True,
) -> dict[str, Any]:
    started = time.time()
    vector_results: list[dict[str, Any]] = []
    fallback_used = False
    fallback_reason = ""
    manifest: dict[str, Any] = {}
    try:
        vector_response = vector_store.search(query, index_dir=index_dir, top_k=vector_top_k)
        vector_results = vector_response.get("results") or []
        manifest = vector_response.get("manifest") or {}
    except Exception as exc:  # noqa: BLE001
        if not allow_keyword_fallback:
            raise
        fallback_used = True
        fallback_reason = str(exc)

    keyword_limited = keyword_results[:keyword_top_k]
    hybrid_results = combine_results(vector_results, keyword_limited)
    if rerank_enabled and hybrid_results:
        reranker_output = rerank(query, hybrid_results[: max(vector_top_k, 6)], final_top_n=final_top_n)
        selected = reranker_output.get("rankedResults") or []
    else:
        reranker_output = {
            "query": query,
            "rerankerModel": "",
            "fallbackUsed": False,
            "rankedResults": hybrid_results[:final_top_n],
            "allRankedResults": hybrid_results,
            "elapsedSeconds": 0,
        }
        selected = hybrid_results[:final_top_n]

    return {
        "query": query,
        "retrievalMode": "hybrid-rerank" if rerank_enabled else "hybrid",
        "embeddingModel": manifest.get("embeddingModel") or os.environ.get("LOCAL_EMBEDDING_MODEL", "nomic-embed-text"),
        "embeddingDimension": manifest.get("embeddingDimension"),
        "rerankerModel": reranker_output.get("rerankerModel") or "",
        "fallbackUsed": fallback_used or bool(reranker_output.get("fallbackUsed")),
        "fallbackReason": fallback_reason,
        "vectorSearchResults": vector_results,
        "keywordSearchResults": keyword_limited,
        "hybridResults": hybrid_results,
        "rerankedResults": reranker_output.get("rankedResults") or [],
        "rerankerOutput": reranker_output,
        "selectedContext": selected,
        "elapsedSeconds": round(time.time() - started, 3),
    }


def combine_results(vector_results: list[dict[str, Any]], keyword_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    vector_scores = [float(item.get("vectorScore") or 0.0) for item in vector_results]
    keyword_scores = [float(item.get("score") or item.get("keywordScore") or 0.0) for item in keyword_results]
    min_vector = min(vector_scores) if vector_scores else 0.0
    max_vector = max(vector_scores) if vector_scores else 1.0
    max_keyword = max(keyword_scores) if keyword_scores else 1.0
    combined: dict[str, dict[str, Any]] = {}

    for item in vector_results:
        key = result_key(item)
        row = normalize_item(item)
        row["vectorScore"] = normalize_range(float(item.get("vectorScore") or 0.0), min_vector, max_vector)
        row["keywordScore"] = 0.0
        combined[key] = row

    for item in keyword_results:
        key = result_key(item)
        row = combined.get(key) or normalize_item(item)
        row["keywordScore"] = normalize_keyword(float(item.get("score") or item.get("keywordScore") or 0.0), max_keyword)
        row["matchedKeywords"] = item.get("matchedKeywords") or row.get("matchedKeywords") or []
        combined[key] = row

    results = []
    for row in combined.values():
        vector_score = float(row.get("vectorScore") or 0.0)
        keyword_score = float(row.get("keywordScore") or 0.0)
        row["combinedScore"] = round(vector_score * DEFAULT_VECTOR_WEIGHT + keyword_score * DEFAULT_KEYWORD_WEIGHT, 6)
        results.append(row)
    results.sort(key=lambda item: (-float(item.get("combinedScore") or 0.0), str(item.get("sourcePath") or item.get("path"))))
    return results


def result_key(item: dict[str, Any]) -> str:
    return str(item.get("sourcePath") or item.get("path") or item.get("chunkId") or "")


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    source_path = item.get("sourcePath") or item.get("path") or ""
    return {
        "sourcePath": source_path,
        "path": source_path,
        "title": item.get("title") or "",
        "category": item.get("category") or "",
        "heading": item.get("heading") or "",
        "chunkId": item.get("chunkId") or source_path,
        "content": item.get("content") or item.get("excerpt") or "",
        "excerpt": item.get("excerpt") or item.get("content") or "",
        "matchedKeywords": item.get("matchedKeywords") or [],
    }


def normalize_range(value: float, min_value: float, max_value: float) -> float:
    if max_value <= min_value:
        return 1.0 if value else 0.0
    return (value - min_value) / (max_value - min_value)


def normalize_keyword(value: float, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return value / max_value


def main() -> int:
    from agent.rag.retriever import keyword_search

    parser = argparse.ArgumentParser(description="Run hybrid RAG search.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--knowledge-base", default=str(vector_store.DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--index-dir", default=str(vector_store.DEFAULT_INDEX_DIR))
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--final-top-n", type=int, default=3)
    args = parser.parse_args()
    keywords = keyword_search(args.query, args.knowledge_base, limit=5)
    result = hybrid_search(args.query, keywords, args.knowledge_base, args.index_dir, args.top_k, 5, args.final_top_n)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
