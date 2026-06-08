#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_BIN="$ROOT_DIR/.tools/bin"

export PATH="$LOCAL_BIN:$PATH"

echo "PATH prepared with $LOCAL_BIN"
echo "Run './scripts/check-env.sh' to verify the environment."
exec "${SHELL:-/bin/bash}"
