# Invalid Field Type Recovery Example

metadata:
- source: internal-authored
- category: example
- scenario: recovery

## Situation

A requirement contains `brokenValue:notatype`. The artifact patcher renders this into the API type file, and
`make generate` fails because `notatype` is not a known Go type.

## Correct Recovery Plan

The first recovery step is requirement or operator-spec correction. Replace `notatype` with a supported type such as
`string`, `int32`, `bool`, or `map[string]string`. After approval, regenerate the operator spec, patch the artifact,
then run `make generate`, `make manifests`, and `make test`.

## Incorrect Recovery Plan

Rerunning `controller-gen` or checking the Go version does not fix the unsupported field type. Those actions should be
rejected unless there is separate log evidence that the binary or Go version caused the failure.
