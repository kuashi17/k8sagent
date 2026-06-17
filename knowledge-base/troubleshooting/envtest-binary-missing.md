# Envtest Binary Missing

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: make test

## Symptom

`make test` fails while trying to start envtest or Kubernetes API server binaries. Logs mention missing `etcd`,
`kube-apiserver`, or `setup-envtest`.

## Root Cause

Kubebuilder controller tests often use envtest. The Go test binary can compile, but the local Kubernetes test binaries
must also be available. Version mismatches can happen when the Kubernetes dependency and envtest binary version drift.

## Recovery

Run the project Makefile test setup from the Kubebuilder project root. Check the `ENVTEST_K8S_VERSION` in the Makefile
and ensure the setup-envtest tool can download or locate matching binaries. In offline environments, pre-stage the
envtest binaries.
