# Few-Shot: Successful Execution Evaluation

metadata:
- source: internal-authored
- category: few-shot
- use: final-evaluation

## Input Evidence

Tool results show spec generation exitCode 0, command plan exitCode 0, scaffold exitCode 0, artifact patch exitCode 0,
and validation commands `make generate`, `make manifests`, `make test` all exitCode 0.

## Expected Decision

Return `executionDecision: succeeded`. Include generated artifacts such as API type file, CRD manifest, RBAC manifest,
sample YAML, command plan, and agent report. Beginner summary should say that the Operator skeleton and generated
manifests compiled and passed tests.
