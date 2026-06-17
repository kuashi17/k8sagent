#!/usr/bin/env python3
"""Build or check the local FAISS RAG index."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.rag.embedding_client import check_embedding_model
from agent.rag.vector_store import DEFAULT_INDEX_DIR, DEFAULT_KNOWLEDGE_BASE, build_index, load_manifest, manifest_current, resolve_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the local FAISS index for knowledge-base Markdown files.")
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    kb = resolve_path(args.knowledge_base)
    index_dir = resolve_path(args.index_dir)
    if args.check:
        current = manifest_current(kb, index_dir)
        manifest = load_manifest(index_dir) if (index_dir / "index-manifest.json").is_file() else {}
        print(json.dumps({"current": current, "manifest": manifest}, indent=2, ensure_ascii=False))
        return 0 if current else 1

    started = time.time()
    health = check_embedding_model()
    print(f"Embedding model OK: {health['model']} dimension={health['dimension']}")
    manifest = build_index(kb, index_dir, rebuild=args.rebuild, verbose=args.verbose)
    print(f"Index written: {index_dir}")
    print(f"documents={manifest['documentCount']} chunks={manifest['chunkCount']} elapsedSeconds={round(time.time() - started, 3)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
