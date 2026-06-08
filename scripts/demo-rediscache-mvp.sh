#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_BIN="$ROOT_DIR/.tools/bin"
OPERATOR_DIR="$ROOT_DIR/workspace/redis-cache-operator"
SPEC_FILE="$ROOT_DIR/generated/rediscache-operator-spec.yaml"
CONTROLLER_GEN="$OPERATOR_DIR/bin/controller-gen"

export PATH="$LOCAL_BIN:$PATH"
export GOCACHE="${GOCACHE:-/tmp/k8sagent-go-build}"

section() {
  printf '\n== %s ==\n' "$1"
}

run() {
  printf '+ %s\n' "$*"
  "$@"
}

require_file() {
  if [ ! -f "$1" ]; then
    echo "missing required file: $1" >&2
    exit 1
  fi
}

require_dir() {
  if [ ! -d "$1" ]; then
    echo "missing required directory: $1" >&2
    exit 1
  fi
}

section "RedisCache MVP Demo"
echo "This demo checks the generated Kubebuilder RedisCache Operator MVP."
echo "Project root: $ROOT_DIR"

section "1. Environment Check"
if "$ROOT_DIR/scripts/check-env.sh"; then
  echo "Environment check passed."
else
  echo "Environment check reported warnings. Continuing with scaffold verification."
fi

section "2. Structured Requirement Spec"
require_file "$SPEC_FILE"
run sed -n '1,180p' "$SPEC_FILE"

section "3. Generated Operator Artifacts"
require_dir "$OPERATOR_DIR"
run sed -n '1,180p' "$OPERATOR_DIR/api/v1alpha1/rediscache_types.go"
run sed -n '1,180p' "$OPERATOR_DIR/config/samples/cache_v1alpha1_rediscache.yaml"

section "4. controller-gen Version"
require_file "$CONTROLLER_GEN"
run "$CONTROLLER_GEN" --version

section "5. Generate DeepCopy"
(
  cd "$OPERATOR_DIR"
  run "$CONTROLLER_GEN" object:headerFile="hack/boilerplate.go.txt" paths="./..."
)

section "6. Generate CRD Manifest"
(
  cd "$OPERATOR_DIR"
  run "$CONTROLLER_GEN" rbac:roleName=manager-role crd webhook paths="./..." output:crd:artifacts:config=config/crd/bases
)

section "7. Verify CRD Schema"
run grep -n "storageSize\\|readyReplicas\\|phase\\|image\\|size" "$OPERATOR_DIR/config/crd/bases/cache.sample.io_rediscaches.yaml"

section "8. Compile Check"
(
  cd "$OPERATOR_DIR"
  run go test ./api/... ./cmd/... ./test/utils
)

section "Result"
echo "RedisCache MVP demo completed successfully."
echo "Next files to inspect:"
echo "- $OPERATOR_DIR/api/v1alpha1/rediscache_types.go"
echo "- $OPERATOR_DIR/config/crd/bases/cache.sample.io_rediscaches.yaml"
echo "- $OPERATOR_DIR/config/samples/cache_v1alpha1_rediscache.yaml"
