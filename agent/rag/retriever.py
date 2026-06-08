#!/usr/bin/env python3
"""Small local Markdown retriever for the Agent MVP.

This is intentionally keyword-based. It provides a stable RAG-like contract
that can later be replaced by embeddings, a Vector DB, or a reranker.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_DIR = REPO_ROOT / "knowledge-base"
STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "operator",
    "kubernetes",
    "custom",
    "resource",
    "를",
    "을",
    "는",
    "은",
    "이",
    "가",
    "하고",
    "한다",
    "생성",
    "관리",
}


def search(query: str, knowledge_dir: Path | str = DEFAULT_KNOWLEDGE_DIR, limit: int = 5) -> list[dict[str, Any]]:
    base = Path(knowledge_dir)
    if not base.is_absolute():
        base = REPO_ROOT / base
    if not base.is_dir():
        return []

    query_terms = keywords(query)
    results: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        text_terms = set(keywords(text))
        matched = sorted(term for term in query_terms if term in text_terms)
        if not matched:
            continue
        results.append(
            {
                "path": str(path.relative_to(REPO_ROOT)),
                "title": title_of(text, path),
                "matchedKeywords": matched,
                "excerpt": excerpt_for(text, matched),
                "score": len(matched),
            }
        )

    results.sort(key=lambda item: (-item["score"], item["path"]))
    return results[:limit]


def keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9_-]*|[가-힣]{2,}|[a-z0-9.]+/[a-z0-9.-]+", text.lower())
    result: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in STOPWORDS or len(token) <= 1 or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result


def title_of(text: str, path: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def excerpt_for(text: str, matched: list[str]) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    lowered = [(part, part.lower()) for part in paragraphs]
    for term in matched:
        for original, lower in lowered:
            if term in lower:
                return compact(original)
    return compact(paragraphs[0] if paragraphs else "")


def compact(text: str, limit: int = 360) -> str:
    one_line = re.sub(r"\s+", " ", text).strip()
    return one_line if len(one_line) <= limit else f"{one_line[: limit - 3]}..."


def main() -> int:
    parser = argparse.ArgumentParser(description="Search local Agent knowledge-base Markdown files.")
    parser.add_argument("--query", required=True, help="Search query text.")
    parser.add_argument("--knowledge-dir", default=str(DEFAULT_KNOWLEDGE_DIR), help="Knowledge-base directory.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of results.")
    args = parser.parse_args()

    for item in search(args.query, args.knowledge_dir, args.limit):
        print(f"- {item['path']} :: {item['title']}")
        print(f"  keywords: {', '.join(item['matchedKeywords'])}")
        print(f"  excerpt: {item['excerpt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
