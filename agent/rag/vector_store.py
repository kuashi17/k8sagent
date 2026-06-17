#!/usr/bin/env python3
"""FAISS vector store for local knowledge-base chunks."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.rag.document_loader import DEFAULT_KNOWLEDGE_BASE, load_chunks, source_file_hashes
from agent.rag.embedding_client import EmbeddingConfig, config_from_env, embed_text, embed_texts


DEFAULT_INDEX_DIR = DEFAULT_KNOWLEDGE_BASE / ".index"


class VectorStoreError(RuntimeError):
    """Raised when the vector store cannot be used."""


def build_index(
    knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE,
    index_dir: str | Path = DEFAULT_INDEX_DIR,
    rebuild: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    faiss, np = import_vector_dependencies()
    base = resolve_path(knowledge_base)
    target = resolve_path(index_dir)
    target.mkdir(parents=True, exist_ok=True)
    if not rebuild and manifest_current(base, target):
        return load_manifest(target)

    started = time.time()
    chunks = load_chunks(base)
    if not chunks:
        raise VectorStoreError(f"No Markdown chunks found under {base}")

    cfg = config_from_env()
    texts = [chunk["content"] for chunk in chunks]
    embeddings = embed_texts(texts, cfg)
    dimension = len(embeddings[0])
    vectors = np.array(embeddings, dtype="float32")
    faiss.normalize_L2(vectors)
    index = faiss.IndexFlatIP(dimension)
    index.add(vectors)
    faiss.write_index(index, str(target / "faiss.index"))
    metadata = {"chunks": chunks}
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "embeddingModel": cfg.model,
        "embeddingBaseUrl": cfg.base_url,
        "embeddingDimension": dimension,
        "documentCount": len({chunk["documentId"] for chunk in chunks}),
        "chunkCount": len(chunks),
        "createdAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sourceFileHashes": source_file_hashes(base),
        "elapsedSeconds": round(time.time() - started, 3),
    }
    (target / "index-manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    if verbose:
        print(json.dumps(manifest, indent=2, ensure_ascii=False))
    return manifest


def search(
    query: str,
    index_dir: str | Path = DEFAULT_INDEX_DIR,
    top_k: int = 8,
) -> dict[str, Any]:
    faiss, np = import_vector_dependencies()
    target = resolve_path(index_dir)
    index_path = target / "faiss.index"
    metadata_path = target / "metadata.json"
    manifest_path = target / "index-manifest.json"
    if not index_path.is_file() or not metadata_path.is_file() or not manifest_path.is_file():
        raise VectorStoreError(f"FAISS index not found under {target}. Run agent/rag/build_index.py first.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    chunks = metadata.get("chunks") or []
    cfg = EmbeddingConfig(
        base_url=manifest.get("embeddingBaseUrl") or config_from_env().base_url,
        model=manifest.get("embeddingModel") or config_from_env().model,
    )
    query_embedding = np.array([embed_text(query, cfg)], dtype="float32")
    faiss.normalize_L2(query_embedding)
    index = faiss.read_index(str(index_path))
    scores, indexes = index.search(query_embedding, min(top_k, len(chunks)))
    results = []
    for score, idx in zip(scores[0].tolist(), indexes[0].tolist()):
        if idx < 0 or idx >= len(chunks):
            continue
        item = dict(chunks[idx])
        item["vectorScore"] = float(score)
        results.append(item)
    return {"query": query, "retrievalMode": "vector", "manifest": manifest, "results": results}


def manifest_current(knowledge_base: Path, index_dir: Path) -> bool:
    manifest_path = index_dir / "index-manifest.json"
    index_path = index_dir / "faiss.index"
    metadata_path = index_dir / "metadata.json"
    if not manifest_path.is_file() or not index_path.is_file() or not metadata_path.is_file():
        return False
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return manifest.get("sourceFileHashes") == source_file_hashes(knowledge_base)


def load_manifest(index_dir: str | Path = DEFAULT_INDEX_DIR) -> dict[str, Any]:
    path = resolve_path(index_dir) / "index-manifest.json"
    if not path.is_file():
        raise VectorStoreError(f"index-manifest.json not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def import_vector_dependencies():
    try:
        import faiss  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise VectorStoreError("FAISS vector search requires `faiss-cpu` and `numpy`. Install with `pip install -r requirements.txt`.") from exc
    return faiss, np


def resolve_path(path: str | Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        value = REPO_ROOT / value
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Query a FAISS knowledge-base index.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--index-dir", default=str(DEFAULT_INDEX_DIR))
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()
    result = search(args.query, args.index_dir, args.top_k)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
