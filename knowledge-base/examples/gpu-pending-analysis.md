# GPU Pending Analysis Example

metadata:
- source: internal-authored
- category: example
- scenario: environment-warning

## Situation

TrainingJob clean e2e creates a Kubernetes Job with the expected image, PVC mount, `DATASET_PATH`, `OUTPUT_PATH`, and
`nvidia.com/gpu` limit. The Pod remains Pending because kind has no GPU resource.

## Decision

Classify the run as `succeeded-with-warning` when the Operator-generated Job spec is correct and the only blocker is
`Insufficient nvidia.com/gpu`. The warning belongs to the test environment, not to the controller implementation.

## Next Action

Use `gpuCount: 0` for local kind execution tests, or run the same workload on a GPU-enabled cluster to verify Pod
execution.
