#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_DIR="${K8SAGENT_TOOLS_DIR:-$ROOT_DIR/.tools}"
BIN_DIR="$TOOLS_DIR/bin"
TMP_DIR="$TOOLS_DIR/tmp"

GO_VERSION="${GO_VERSION:-1.26.3}"
KIND_VERSION="${KIND_VERSION:-v0.23.0}"
KUBEBUILDER_VERSION="${KUBEBUILDER_VERSION:-4.1.1}"
KUSTOMIZE_VERSION="${KUSTOMIZE_VERSION:-5.4.2}"

OS="$(uname | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"

case "$ARCH" in
  x86_64|amd64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

mkdir -p "$BIN_DIR" "$TMP_DIR"

download() {
  local url="$1"
  local dest="$2"

  echo "Downloading $url"
  curl -fL --retry 3 --retry-delay 2 "$url" -o "$dest"
}

install_go() {
  if [ -x "$BIN_DIR/go" ] && "$BIN_DIR/go" version | grep -q "go${GO_VERSION} "; then
    echo "go already installed: $("$BIN_DIR/go" version)"
    return
  fi

  local archive="$TMP_DIR/go${GO_VERSION}.${OS}-${ARCH}.tar.gz"
  download "https://go.dev/dl/go${GO_VERSION}.${OS}-${ARCH}.tar.gz" "$archive"
  rm -rf "$TOOLS_DIR/go"
  tar -C "$TOOLS_DIR" -xzf "$archive"
  ln -sf "$TOOLS_DIR/go/bin/go" "$BIN_DIR/go"
  ln -sf "$TOOLS_DIR/go/bin/gofmt" "$BIN_DIR/gofmt"
  "$BIN_DIR/go" version
}

install_kind() {
  if [ -x "$BIN_DIR/kind" ]; then
    echo "kind already installed: $("$BIN_DIR/kind" version)"
    return
  fi

  download "https://github.com/kubernetes-sigs/kind/releases/download/${KIND_VERSION}/kind-${OS}-${ARCH}" "$BIN_DIR/kind"
  chmod +x "$BIN_DIR/kind"
  "$BIN_DIR/kind" version
}

install_kubebuilder() {
  if [ -x "$BIN_DIR/kubebuilder" ]; then
    echo "kubebuilder already installed: $("$BIN_DIR/kubebuilder" version)"
    return
  fi

  download "https://github.com/kubernetes-sigs/kubebuilder/releases/download/v${KUBEBUILDER_VERSION}/kubebuilder_${OS}_${ARCH}" "$BIN_DIR/kubebuilder"
  chmod +x "$BIN_DIR/kubebuilder"
  "$BIN_DIR/kubebuilder" version
}

install_kustomize() {
  if [ -x "$BIN_DIR/kustomize" ]; then
    echo "kustomize already installed: $("$BIN_DIR/kustomize" version)"
    return
  fi

  local archive="$TMP_DIR/kustomize_${KUSTOMIZE_VERSION}_${OS}_${ARCH}.tar.gz"
  download "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize/v${KUSTOMIZE_VERSION}/kustomize_v${KUSTOMIZE_VERSION}_${OS}_${ARCH}.tar.gz" "$archive"
  tar -C "$BIN_DIR" -xzf "$archive" kustomize
  chmod +x "$BIN_DIR/kustomize"
  "$BIN_DIR/kustomize" version
}

install_go
install_kind
install_kubebuilder
install_kustomize

cat <<EOF

Local tools installed in:
  $BIN_DIR

For this shell session:
  export PATH="$BIN_DIR:\$PATH"

Then verify with:
  ./scripts/check-env.sh
EOF
