# Few-Shot: Invalid Field Type Recovery Plan

metadata:
- source: internal-authored
- category: few-shot
- use: recovery-planning

## Input Evidence

`make generate` fails with `undefined: notatype` near an API field such as `brokenValue`. The field type is not in the
supported type allowlist.

## Expected Recovery Plan

Classify as `invalid-field-type`. Proposed recovery starts with requirement or operator spec correction, then
spec_generator, artifact_patcher, and validation. Every recovery tool call requires approval. Reject `controller-gen`
or arbitrary shell commands because they do not correct the invalid type.
