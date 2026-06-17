# Invalid Go Field Type

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: api type generation, controller-gen, make generate

## Symptom

`make generate` or `controller-gen` fails after API type fields are patched into `api/<version>/*_types.go`.
Typical messages include `undefined: notatype`, `expected type`, `unknown identifier`, or Go compile errors in an API package.

## Root Cause

Kubebuilder CRD structs must use Go types that controller-gen can understand. Common supported scalar fields include
`string`, `bool`, `int`, `int32`, `int64`, `float32`, and `float64`. Common collection fields include `[]string`
and `map[string]string`. If a requirement file contains a type such as `notatype`, the generated Go struct compiles
incorrectly and downstream CRD generation cannot continue.

## Recovery

Correct the requirement or operator spec first. Regenerating controller-gen output does not fix the underlying type.
After the type is corrected, rerun spec generation or artifact patching, then run `make generate`, `make manifests`,
and `make test`.

## Evidence To Check

Look for the field name near the compile error. If the error mentions a user-defined field such as `brokenValue` and
the type token is unsupported, classify the issue as `invalid-field-type`. Recovery should start from requirement or
operator-spec correction and require user approval before modifying files.
