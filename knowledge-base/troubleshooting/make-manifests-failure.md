# Make Manifests Failure

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: CRD, RBAC, webhook manifest generation

## Symptom

`make manifests` fails or produces incomplete files under `config/crd` or `config/rbac`. Logs may reference RBAC marker
syntax, CRD schema generation, or webhook certificate/manifests.

## Common Causes

- invalid RBAC marker syntax in the controller file
- unsupported API field type in the CRD schema
- missing status subresource marker
- controller-gen version mismatch
- webhook marker or certificate configuration that does not match the scaffold

## Recovery

Inspect the controller file for `+kubebuilder:rbac` markers and the API type file for schema markers. If the issue is
RBAC related, regenerate markers from `operator-spec.yaml` `rbac.resources`, then run `make manifests` again.
