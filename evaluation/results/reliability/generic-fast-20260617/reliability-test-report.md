# Agent Reliability Test Report

- Overall status: `passed`
- Level: `fast`
- Fixture: `generic-configmap-fixture`
- Fixture requirement: `requirements/appconfig.txt`
- Fixture profile: `profiles/appconfig.yaml`
- Created at: `2026-06-17T21:33:42+09:00`

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

## Generic Fixture Agent Dry-Run Consistency

- Status: `passed`
- Runs: `1`
- Run 1: exitCode=`0` logDir=`logs/agent/20260617-213131-724441`

## Generic Fixture Kind Idempotency

- Status: `skipped`
- Reapply idempotent: `None`
- Spec change idempotent: `None`
- Fixture CR status: `{}`

## Generated Result Files

- `reliability-test-results.json`
- `consistency-results.json`
- `kind-idempotency-results.json`
- `reliability-test-report.md`
