#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export RAG_MODE="${RAG_MODE:-hybrid}"
export RAG_RERANK_ENABLED="${RAG_RERANK_ENABLED:-false}"

python3 agent/rag/build_index.py \
  --knowledge-base knowledge-base \
  --index-dir knowledge-base/.index \
  --rebuild

python3 agent/evaluation/rag_evaluator.py \
  --dataset evaluation/rag-evaluation-dataset.yaml \
  --index-dir knowledge-base/.index \
  --modes "${RAG_EVALUATION_MODES:-keyword,vector,hybrid}" \
  --output-dir evaluation/results
