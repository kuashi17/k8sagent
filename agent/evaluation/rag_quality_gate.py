#!/usr/bin/env python3
"""Offline keyword/selection quality gate for requirement RAG fixtures."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.evaluation_metrics import compute_mode_metrics, summarize_query_result  # noqa: E402
from agent.rag.retriever import search_detailed  # noqa: E402
from agent.retrieval_context import select_context  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default="evaluation/rag-evaluation-dataset.yaml",
    )
    parser.add_argument("--output", default="")
    parser.add_argument("--min-hit-at-3", type=float, default=0.8)
    args = parser.parse_args()

    dataset_path = resolve(args.dataset)
    data = yaml.safe_load(dataset_path.read_text(encoding="utf-8")) or {}
    queries = [
        item
        for item in data.get("queries") or []
        if item.get("category") == "requirement"
    ]
    results = []
    for item in queries:
        response = search_detailed(item["query"], limit=8, mode="keyword")
        response["selectedContext"] = select_context(
            {"hybridResults": response.get("selectedContext") or []},
            3,
            "requirement",
        )
        results.append(summarize_query_result(item, response, 0.0))

    metrics = compute_mode_metrics(results)
    payload = {
        "status": (
            "passed"
            if metrics["hitAt3"] >= args.min_hit_at_3
            else "failed"
        ),
        "thresholds": {"minHitAt3": args.min_hit_at_3},
        "metrics": metrics,
        "results": results,
    }
    if args.output:
        output = resolve(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0 if payload["status"] == "passed" else 1


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
