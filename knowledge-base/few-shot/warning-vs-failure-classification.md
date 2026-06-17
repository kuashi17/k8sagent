# Few-Shot: Warning Versus Failure Classification

metadata:
- source: internal-authored
- category: few-shot
- use: log-analysis

## Warning Example

If a TrainingJob Job spec validation passes but the Pod is Pending with `Insufficient nvidia.com/gpu`, classify the run
as `succeeded-with-warning`. The controller created the expected Kubernetes Job, and the warning is caused by the local
cluster capacity.

## Failure Example

If the controller does not create the expected Job, or the Job spec does not contain required image, env, volume, or GPU
fields, classify as failed. Environment warnings should not hide missing controller behavior.
