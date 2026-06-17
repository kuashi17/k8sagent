#!/usr/bin/env python3
"""Local Markdown retriever with keyword, vector, hybrid, and rerank modes."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_KNOWLEDGE_DIR = REPO_ROOT / "knowledge-base"
DEFAULT_INDEX_DIR = DEFAULT_KNOWLEDGE_DIR / ".index"
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


def search(
    query: str,
    knowledge_dir: Path | str = DEFAULT_KNOWLEDGE_DIR,
    limit: int = 5,
    mode: str | None = None,
) -> list[dict[str, Any]]:
    """Backward compatible search API used by the Agent.

    It returns the final selected context list, shaped like the old keyword
    results where possible: path, title, matchedKeywords, excerpt, score.
    """

    detailed = search_detailed(query, knowledge_dir, limit=limit, mode=mode)
    return [compat_result(item) for item in detailed["selectedContext"][:limit]]


def search_detailed(
    query: str,
    knowledge_dir: Path | str = DEFAULT_KNOWLEDGE_DIR,
    limit: int = 5,
    mode: str | None = None,
) -> dict[str, Any]:
    mode = mode or os.environ.get("RAG_MODE", "hybrid")
    top_k = int(os.environ.get("RAG_TOP_K", "8"))
    final_top_n = int(os.environ.get("RAG_FINAL_TOP_N", str(limit)))
    rerank_enabled = os.environ.get("RAG_RERANK_ENABLED", "false").lower() not in {"0", "false", "no"}
    allow_keyword_fallback = os.environ.get("RAG_KEYWORD_FALLBACK", "true").lower() not in {"0", "false", "no"}
    base = resolve_knowledge_dir(knowledge_dir)
    keyword_results = keyword_search(query, base, limit=max(limit, 5))

    if mode == "keyword":
        return {
            "query": query,
            "retrievalMode": "keyword",
            "fallbackUsed": False,
            "fallbackReason": "",
            "vectorSearchResults": [],
            "keywordSearchResults": keyword_results,
            "hybridResults": [],
            "rerankedResults": [],
            "selectedContext": keyword_results[:limit],
            "embeddingModel": "",
            "rerankerModel": "",
        }

    try:
        if mode == "vector":
            from agent.rag.vector_store import search as vector_search

            vector_response = vector_search(query, DEFAULT_INDEX_DIR, top_k=top_k)
            vector_results = vector_response.get("results") or []
            manifest = vector_response.get("manifest") or {}
            return {
                "query": query,
                "retrievalMode": "vector",
                "fallbackUsed": False,
                "fallbackReason": "",
                "vectorSearchResults": vector_results,
                "keywordSearchResults": keyword_results,
                "hybridResults": vector_results,
                "rerankedResults": [],
                "selectedContext": vector_results[:limit],
                "embeddingModel": manifest.get("embeddingModel") or "",
                "embeddingDimension": manifest.get("embeddingDimension"),
                "rerankerModel": "",
            }
        if mode in {"hybrid", "hybrid-rerank"}:
            from agent.rag.hybrid_retriever import hybrid_search

            return hybrid_search(
                query,
                keyword_results,
                knowledge_base=base,
                index_dir=DEFAULT_INDEX_DIR,
                vector_top_k=top_k,
                keyword_top_k=max(5, limit),
                final_top_n=final_top_n,
                rerank_enabled=(mode == "hybrid-rerank" and rerank_enabled),
                allow_keyword_fallback=allow_keyword_fallback,
            )
    except Exception as exc:  # noqa: BLE001
        if not allow_keyword_fallback:
            raise
        return {
            "query": query,
            "retrievalMode": mode,
            "fallbackUsed": True,
            "fallbackReason": str(exc),
            "vectorSearchResults": [],
            "keywordSearchResults": keyword_results,
            "hybridResults": keyword_results,
            "rerankedResults": [],
            "selectedContext": keyword_results[:limit],
            "embeddingModel": os.environ.get("LOCAL_EMBEDDING_MODEL", "nomic-embed-text"),
            "rerankerModel": "",
        }

    raise ValueError(f"Unsupported RAG_MODE: {mode}")


def keyword_search(query: str, knowledge_dir: Path | str = DEFAULT_KNOWLEDGE_DIR, limit: int = 5) -> list[dict[str, Any]]:
    base = resolve_knowledge_dir(knowledge_dir)
    if not base.is_dir():
        return []

    query_terms = keywords(query)
    results: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.md")):
        if ".index" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        text_terms = set(keywords(text))
        matched = sorted(term for term in query_terms if term in text_terms)
        if not matched:
            continue
        rel_path = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        results.append(
            {
                "path": rel_path,
                "sourcePath": rel_path,
                "chunkId": rel_path,
                "title": title_of(text, path),
                "category": category_for(path),
                "matchedKeywords": matched,
                "excerpt": excerpt_for(text, matched),
                "content": excerpt_for(text, matched, limit=900),
                "score": len(matched),
                "keywordScore": float(len(matched)),
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


def excerpt_for(text: str, matched: list[str], limit: int = 360) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    lowered = [(part, part.lower()) for part in paragraphs]
    for term in matched:
        for original, lower in lowered:
            if term in lower:
                return compact(original, limit)
    return compact(paragraphs[0] if paragraphs else "", limit)


def compact(text: str, limit: int = 360) -> str:
    one_line = re.sub(r"\s+", " ", text).strip()
    return one_line if len(one_line) <= limit else f"{one_line[: limit - 3]}..."


def compat_result(item: dict[str, Any]) -> dict[str, Any]:
    path = item.get("path") or item.get("sourcePath") or ""
    excerpt = item.get("excerpt") or item.get("content") or ""
    return {
        "path": path,
        "sourcePath": path,
        "chunkId": item.get("chunkId") or path,
        "title": item.get("title", ""),
        "category": item.get("category", ""),
        "matchedKeywords": item.get("matchedKeywords") or [],
        "excerpt": compact(str(excerpt), 900),
        "content": str(item.get("content") or excerpt),
        "score": item.get("combinedScore", item.get("score", item.get("vectorScore", 0))),
        "vectorScore": item.get("vectorScore"),
        "keywordScore": item.get("keywordScore"),
        "combinedScore": item.get("combinedScore"),
        "rerankScore": item.get("rerankScore"),
        "reason": item.get("reason"),
    }


def category_for(path: Path) -> str:
    parts = set(path.parts)
    if "troubleshooting" in parts:
        return "troubleshooting"
    if "examples" in parts:
        return "example"
    if "few-shot" in parts:
        return "few-shot"
    return "guide"


def resolve_knowledge_dir(path: Path | str) -> Path:
    base = Path(path)
    if not base.is_absolute():
        base = REPO_ROOT / base
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description="Search local Agent knowledge-base Markdown files.")
    parser.add_argument("--query", required=True, help="Search query text.")
    parser.add_argument("--knowledge-dir", default=str(DEFAULT_KNOWLEDGE_DIR), help="Knowledge-base directory.")
    parser.add_argument("--limit", type=int, default=5, help="Maximum number of results.")
    parser.add_argument("--mode", default=os.environ.get("RAG_MODE", "hybrid"), choices=["keyword", "vector", "hybrid", "hybrid-rerank"])
    parser.add_argument("--json", action="store_true", help="Print detailed JSON.")
    args = parser.parse_args()

    detailed = search_detailed(args.query, args.knowledge_dir, args.limit, args.mode)
    if args.json:
        print(json.dumps(detailed, indent=2, ensure_ascii=False))
        return 0
    for item in detailed["selectedContext"]:
        print(f"- {item.get('sourcePath') or item.get('path')} :: {item.get('title')}")
        print(f"  score: {item.get('combinedScore', item.get('score'))}")
        print(f"  excerpt: {compact(str(item.get('content') or item.get('excerpt') or ''), 360)}")
    if detailed.get("fallbackUsed"):
        print(f"fallbackUsed: {detailed.get('fallbackReason')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
