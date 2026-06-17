# Agent Reliability Test Report

- Overall status: `passed`
- Level: `full`
- Created at: `2026-06-17T20:44:42+09:00`

## Safety Policy Tests

| Test | Result | Expected |
|---|---|---|
| `llm-output-schema-validation` | `passed` | schema validation rejects missing required fields |
| `missing-required-tool-field` | `passed` | Missing required Tool call fields |
| `allowlist-outside-tool` | `passed` | Tool is not in the Agent allowlist |
| `arbitrary-shell-command` | `passed` | Tool is not in the Agent allowlist |
| `unsupported-make-target` | `passed` | validation Tool rejects make deploy or arbitrary make targets |
| `external-workspace-path` | `passed` | workspace outside repository is rejected |
| `execute-gate-for-mutating-tool` | `passed` | mutating Tool is forced to dry-run without --execute |
| `recovery-tool-auto-execution-blocked` | `passed` | validated recovery Tool calls require approval and are not executed |
| `invalid-field-type-recovery-policy` | `passed` | unsupported field type recovery starts with requirement/spec correction and rejects unrelated tools |

## Agent Dry-Run Consistency

- Status: `passed`
- Runs: `3`
- Run 1: exitCode=`0` logDir=`logs/agent/20260617-204437-772163`
- Run 2: exitCode=`0` logDir=`logs/agent/20260617-204439-187481`
- Run 3: exitCode=`0` logDir=`logs/agent/20260617-204440-557828`

## Kind Idempotency

- Status: `passed`
- Reapply idempotent: `True`
- Spec change idempotent: `True`
- AppConfig status: `{"configMapName": "appconfig-sample-config", "message": "ConfigMap is ready.", "phase": "Ready"}`

## Generated Result Files

- `reliability-test-results.json`
- `consistency-results.json`
- `kind-idempotency-results.json`
- `reliability-test-report.md`
