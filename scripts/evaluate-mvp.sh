#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 agent/evaluation/mvp_evaluator.py \
  --baseline evaluation/mvp-baseline.yaml \
  --output-dir evaluation/results/mvp \
  "$@"
