# Development Environment

This project expects a local WSL/Linux environment that can run Kubebuilder and Kubernetes tooling.

## Installed Locally

Use the project-local installer when system package installation is unavailable.

```bash
./scripts/install-local-tools.sh
```

The installer places binaries under:

```text
.tools/bin
```

It installs:

- Go
- kind
- kubebuilder
- kustomize

Existing system tools such as `kubectl`, `helm`, `git`, and `docker` are reused from `PATH`.

## Shell Setup

For one shell session:

```bash
export PATH="/home/ch0618/k8sagent/.tools/bin:$PATH"
```

Or start a project shell:

```bash
./scripts/dev-shell.sh
```

## Verify

```bash
./scripts/check-env.sh
```

Expected tools:

- `go`
- `docker`
- `kubectl`
- `kind`
- `helm`
- `kubebuilder`
- `kustomize`
- `git`

## Docker On WSL

Kubebuilder and kind workflows need a working Docker daemon.

If `./scripts/check-env.sh` reports that Docker cannot connect to `unix:///var/run/docker.sock`, enable Docker Desktop WSL integration for this distro or start/configure a Docker daemon inside WSL.

For Docker Desktop:

1. Open Docker Desktop on Windows.
2. Go to Settings > Resources > WSL integration.
3. Enable integration for this WSL distro.
4. Restart the WSL terminal.
5. Run `docker version` and `./scripts/check-env.sh` again.
