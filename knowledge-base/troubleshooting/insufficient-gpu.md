# Insufficient NVIDIA GPU

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: TrainingJob, GPU workloads, kind e2e

## Symptom

A Pod remains Pending and events mention `Insufficient nvidia.com/gpu`. The Job spec includes
`resources.limits["nvidia.com/gpu"]`, but the local kind cluster has no GPU allocatable resource.

## Interpretation

This is an environment warning, not necessarily a controller failure. If Job spec validation confirms that the requested
GPU limit was rendered correctly, the Operator satisfied its contract. Pod execution requires a cluster with GPU nodes
or a test sample with `gpuCount: 0`.

## Recovery

For local kind e2e, use a GPU-free sample or set `gpuCount: 0`. For production validation, run the same sample on a GPU
cluster with the NVIDIA device plugin installed.
