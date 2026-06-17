# Controller Gen Failure

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: make generate, make manifests

## Symptom

`controller-gen` exits with a non-zero status while `make generate` or `make manifests` is running. The log may mention
marker parsing, unknown fields, unsupported API types, or a missing controller-gen binary.

## Diagnosis

First separate binary problems from source problems. If the log says `controller-gen: command not found`, check the
Kubebuilder Makefile tool installation. If the log points to `api/..._types.go`, inspect the API struct fields and
Kubebuilder validation markers. If the log points to `internal/controller/..._controller.go`, inspect RBAC markers.

## Recovery

For missing tools, rerun the Makefile target that installs controller-gen or run `make generate` from the project root.
For invalid markers or Go types, fix the source file first. Rerunning controller-gen alone is not a recovery plan when
the source still contains invalid fields or malformed markers.
