#!/usr/bin/env python3
"""Evaluate local RAG retrieval modes against a labeled query dataset."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.evaluation_metrics import compute_mode_metrics, summarize_query_result
from agent.evaluation.report_generator import write_report
from agent.rag.document_loader import load_chunks
from agent.rag.retriever import search_detailed


DEFAULT_DATASET = REPO_ROOT / "evaluation" / "rag-evaluation-dataset.yaml"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "evaluation" / "results"
DEFAULT_INDEX_DIR = REPO_ROOT / "knowledge-base" / ".index"


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate keyword/vector/hybrid RAG retrieval quality.")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--modes", default="keyword,vector,hybrid,hybrid-rerank")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--skip-reranker", action="store_true")
    parser.add_argument("--reranker-timeout", type=int, default=None)
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    dataset_path = resolve_path(args.dataset)
    dataset = load_dataset(dataset_path)
    requested_modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    modes = [mode for mode in requested_modes if not (args.skip_reranker and mode == "hybrid-rerank")]
    output_root = resolve_path(args.output_dir) / datetime.now().strftime("%Y%m%d-%H%M%S")
    output_root.mkdir(parents=True, exist_ok=True)

    details: dict[str, Any] = {"dataset": str(dataset_path.relative_to(REPO_ROOT)), "modes": {}}
    summary: dict[str, Any] = {
        "dataset": str(dataset_path.relative_to(REPO_ROOT)),
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "queryCount": len(dataset["queries"]),
        "documentCount": len({chunk["documentId"] for chunk in load_chunks()}),
        "chunkCount": len(load_chunks()),
        "modes": {},
        "failedQueries": [],
        "mostImprovedQueries": [],
    }

    previous_env = snapshot_env()
    try:
        for mode in modes:
            mode_results = evaluate_mode(dataset["queries"], mode, args.index_dir, args.limit, args.reranker_timeout)
            details["modes"][mode] = mode_results
            summary["modes"][mode] = compute_mode_metrics(mode_results)
            (output_root / f"{mode}-results.json").write_text(json.dumps(mode_results, indent=2, ensure_ascii=False), encoding="utf-8")
    finally:
        restore_env(previous_env)

    summary["failedQueries"] = failed_queries(details)
    summary["mostImprovedQueries"] = improved_queries(details)
    (output_root / "evaluation-summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (output_root / "evaluation-details.json").write_text(json.dumps(details, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(output_root / "rag-evaluation-report.md", summary, details)
    print(f"Evaluation written: {output_root}")
    print(json.dumps(summary["modes"], indent=2, ensure_ascii=False))
    return 0


def evaluate_mode(
    queries: list[dict[str, Any]],
    mode: str,
    index_dir: str,
    limit: int,
    reranker_timeout: int | None,
) -> list[dict[str, Any]]:
    os.environ["RAG_MODE"] = mode
    os.environ["RAG_FINAL_TOP_N"] = str(limit)
    os.environ["RAG_TOP_K"] = str(max(8, limit))
    os.environ["RAG_RERANK_ENABLED"] = "true" if mode == "hybrid-rerank" else "false"
    os.environ["RAG_KEYWORD_FALLBACK"] = "true"
    if reranker_timeout is not None:
        os.environ["LOCAL_LLM_TIMEOUT_SECONDS"] = str(reranker_timeout)
    results = []
    for item in queries:
        started = time.time()
        try:
            response = search_detailed(item["query"], limit=limit, mode=mode)
        except Exception as exc:  # noqa: BLE001
            elapsed = time.time() - started
            response = {
                "query": item["query"],
                "retrievalMode": mode,
                "selectedContext": [],
                "fallbackUsed": True,
                "fallbackReason": str(exc),
            }
        elapsed = time.time() - started
        result = summarize_query_result(item, response, elapsed)
        result["mode"] = mode
        result["retrievalMode"] = response.get("retrievalMode")
        result["embeddingModel"] = response.get("embeddingModel")
        result["rerankerModel"] = response.get("rerankerModel")
        results.append(result)
    return results


def load_dataset(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    queries = data.get("queries") or []
    if not queries:
        raise ValueError(f"No queries found in dataset: {path}")
    return {"metadata": data.get("metadata") or {}, "queries": queries}


def failed_queries(details: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for mode, items in details.get("modes", {}).items():
        for item in items:
            if not item.get("success"):
                rows.append({"mode": mode, "id": item.get("id"), "query": item.get("query")})
    return rows


def improved_queries(details: dict[str, Any]) -> list[dict[str, Any]]:
    keyword = {item.get("id"): item for item in details.get("modes", {}).get("keyword", [])}
    hybrid = {item.get("id"): item for item in details.get("modes", {}).get("hybrid", [])}
    rows = []
    for query_id, hybrid_item in hybrid.items():
        keyword_rank = keyword.get(query_id, {}).get("firstRelevantRank")
        hybrid_rank = hybrid_item.get("firstRelevantRank")
        if keyword_rank and hybrid_rank and hybrid_rank < keyword_rank:
            rows.append({"id": query_id, "keywordRank": keyword_rank, "hybridRank": hybrid_rank})
        elif not keyword_rank and hybrid_rank:
            rows.append({"id": query_id, "keywordRank": None, "hybridRank": hybrid_rank})
    return rows[:10]


def snapshot_env() -> dict[str, str | None]:
    keys = ["RAG_MODE", "RAG_FINAL_TOP_N", "RAG_TOP_K", "RAG_RERANK_ENABLED", "RAG_KEYWORD_FALLBACK", "LOCAL_LLM_TIMEOUT_SECONDS"]
    return {key: os.environ.get(key) for key in keys}


def restore_env(snapshot: dict[str, str | None]) -> None:
    for key, value in snapshot.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def resolve_path(path: str | Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        value = REPO_ROOT / value
    return value


if __name__ == "__main__":
    raise SystemExit(main())
