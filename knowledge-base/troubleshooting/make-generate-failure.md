# Make Generate Failure

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: deepcopy generation

## Symptom

`make generate` fails before generated deepcopy files are updated. The failure often appears after API structs have been
changed by an artifact patcher.

## Common Causes

- unsupported Go field type in `api/<version>/*_types.go`
- missing import for a type used by the API struct
- malformed Kubebuilder marker
- controller-gen installation problem
- command executed outside the Kubebuilder project root

## Recovery

Check the first compile or marker error in stdout/stderr. If an API field is invalid, fix the requirement or spec and
patch the API type again. If the command ran from the wrong directory, rerun from the directory that contains `Makefile`
and `PROJECT`.
