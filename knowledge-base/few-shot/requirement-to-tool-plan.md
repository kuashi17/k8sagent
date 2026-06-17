# Few-Shot: Requirement To Tool Plan

metadata:
- source: internal-authored
- category: few-shot
- use: tool-planning

## Safe Dry-Run Tool Plan

For a new Operator requirement, call `spec_generator` to create `generated/<kind>-operator-spec.yaml`, then call
`command_planner` to create `generated/<kind>-command-plan.md`, then call `scaffold_runner` in dry-run mode. Do not call
`artifact_patcher`, `e2e_runner`, or destructive commands before the scaffold exists and the user explicitly requests
execution.

## Execute Tool Plan

When the user passes `--execute`, the Agent may run scaffold and patch tools through the wrapper allowlist. Validation
is limited to `make generate`, `make manifests`, and `make test`.
