#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_BIN="$ROOT_DIR/.tools/bin"

if [ -d "$LOCAL_BIN" ]; then
  export PATH="$LOCAL_BIN:$PATH"
fi

status=0

print_row() {
  printf '%-12s %-12s %s\n' "$1" "$2" "$3"
}

check_cmd() {
  local name="$1"
  shift

  if ! command -v "$name" >/dev/null 2>&1; then
    print_row "$name" "missing" "not found in PATH"
    status=1
    return
  fi

  local output
  if output="$("$@" 2>&1)"; then
    print_row "$name" "ok" "$(echo "$output" | head -n 1)"
  else
    print_row "$name" "warning" "$(echo "$output" | head -n 1)"
    status=1
  fi
}

printf 'Local bin: %s\n\n' "$LOCAL_BIN"
print_row "tool" "status" "version/result"
print_row "----" "------" "--------------"

check_cmd go go version
check_cmd kubectl kubectl version --client=true
check_cmd kind kind version
check_cmd helm helm version --short
check_cmd kubebuilder kubebuilder version
check_cmd kustomize kustomize version
check_cmd git git --version

if ! command -v docker >/dev/null 2>&1; then
  print_row "docker" "missing" "not found in PATH"
  status=1
elif docker version --format '{{.Client.Version}} / {{.Server.Version}}' >/tmp/k8sagent-docker-version.$$ 2>/tmp/k8sagent-docker-error.$$; then
  print_row "docker" "ok" "$(cat /tmp/k8sagent-docker-version.$$)"
else
  docker_error="$(head -n 1 /tmp/k8sagent-docker-error.$$)"
  if echo "$docker_error" | grep -qi "permission denied" &&
    getent group docker >/dev/null 2>&1 &&
    getent group docker | grep -q "\b$(id -un)\b" &&
    ! id -nG | tr ' ' '\n' | grep -qx docker; then
    print_row "docker" "warning" "docker group not active in this shell; restart WSL or run 'newgrp docker'"
  else
    print_row "docker" "warning" "${docker_error:-client exists, daemon unavailable}"
  fi
  status=1
fi

rm -f /tmp/k8sagent-docker-version.$$ /tmp/k8sagent-docker-error.$$

exit "$status"
