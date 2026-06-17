#!/usr/bin/env python3
"""Markdown report generation for RAG evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_report(summary: dict[str, Any], details: dict[str, Any]) -> str:
    lines = [
        "# RAG Evaluation Report",
        "",
        f"- Dataset: `{summary.get('dataset')}`",
        f"- Generated At: {summary.get('generatedAt')}",
        f"- Query Count: {summary.get('queryCount')}",
        f"- Document Count: {summary.get('documentCount')}",
        f"- Chunk Count: {summary.get('chunkCount')}",
        "",
        "## Mode Metrics",
        "",
        "| Mode | Hit@1 | Hit@3 | Recall@3 | Recall@5 | MRR | Avg Latency | P95 Latency | Fallback | Timeout |",
        "|------|------:|------:|---------:|---------:|----:|------------:|------------:|---------:|--------:|",
    ]
    for mode, metrics in summary.get("modes", {}).items():
        lines.append(
            "| {mode} | {hit1:.4f} | {hit3:.4f} | {recall3:.4f} | {recall5:.4f} | {mrr:.4f} | {avg:.4f}s | {p95:.4f}s | {fallback} | {timeout} |".format(
                mode=mode,
                hit1=float(metrics.get("hitAt1") or 0.0),
                hit3=float(metrics.get("hitAt3") or 0.0),
                recall3=float(metrics.get("recallAt3") or 0.0),
                recall5=float(metrics.get("recallAt5") or 0.0),
                mrr=float(metrics.get("mrr") or 0.0),
                avg=float(metrics.get("avgLatencySeconds") or 0.0),
                p95=float(metrics.get("p95LatencySeconds") or 0.0),
                fallback=int(metrics.get("fallbackCount") or 0),
                timeout=int(metrics.get("rerankerTimeoutCount") or 0),
            )
        )

    lines.extend(["", "## Query Results", ""])
    for mode, mode_details in details.get("modes", {}).items():
        lines.extend([f"### {mode}", ""])
        lines.append("| ID | Category | First Relevant Rank | Recall@5 | Latency | Fallback | Retrieved Sources |")
        lines.append("|----|----------|--------------------:|---------:|--------:|----------|-------------------|")
        for item in mode_details:
            retrieved = "<br>".join(f"`{source}`" for source in item.get("retrievedSources", [])[:5])
            fallback = "yes" if item.get("fallbackUsed") else "no"
            rank = item.get("firstRelevantRank") or "-"
            lines.append(
                f"| {item.get('id')} | {item.get('category')} | {rank} | {float(item.get('recallAt5') or 0.0):.4f} | {float(item.get('elapsedSeconds') or 0.0):.4f}s | {fallback} | {retrieved} |"
            )
        lines.append("")

    failed = summary.get("failedQueries") or []
    if failed:
        lines.extend(["## Search Misses", ""])
        for item in failed:
            lines.append(f"- `{item.get('mode')}` `{item.get('id')}`: {item.get('query')}")
        lines.append("")

    improved = summary.get("mostImprovedQueries") or []
    if improved:
        lines.extend(["## Most Improved Queries", ""])
        for item in improved:
            lines.append(
                f"- `{item.get('id')}`: keyword rank `{item.get('keywordRank')}` -> hybrid rank `{item.get('hybridRank')}`"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_report(path: str | Path, summary: dict[str, Any], details: dict[str, Any]) -> None:
    Path(path).write_text(render_report(summary, details), encoding="utf-8")
