# MVP Evaluation Report

- Generated At: 2026-06-17T14:56:34+09:00
- Baseline Source: placeholder: 기존 수작업 수행 기준 또는 사전 측정값으로 교체 필요
- Baseline Measured: False

## Summary

| 평가 지표 | 목표 | 측정 결과 | 달성 여부 | 근거 |
|---|---:|---:|---|---|
| 작업 시간 단축 | 50% | 측정 데이터 부족 | 측정 불가 | baseline measured=false 또는 execute elapsed 데이터 부족 |
| 산출물 완성도 | 90% | 77.78% | 미달성 | artifact logs=2, requiredArtifacts=9 |
| 1차 검증 통과율 | 80% | 75.0% | 미달성 | measuredSteps=4 |
| 오류 대응 속도 | 10분 이내 | avg 4.433분 / p95 4.433분 | 달성 | failure logs=1 |

## Evaluated Agent Logs

- `logs/agent/20260617-140047-627341` mode=`requirement-planning` agentMode=`dry-run` elapsed=`233.0`
- `logs/agent/20260617-140801-334502` mode=`requirement-planning` agentMode=`execute` elapsed=`267.0`
- `logs/agent/20260617-141235-479378` mode=`log-analysis` agentMode=`` elapsed=`140.0`
- `logs/agent/20260617-141519-779916` mode=`requirement-planning` agentMode=`execute` elapsed=`266.0`

## Artifact Completion

Summary metric uses `requirement-planning` logs with `agentMode=execute`. Other rows are shown for traceability.

| Log | Project | Completion | Missing/Invalid |
|---|---|---:|---|
| `logs/agent/20260617-140047-627341` | `workspace/generated-operators/app-config-operator` | 100.0% | none |
| `logs/agent/20260617-140801-334502` | `workspace/rag-regression-operators/app-config-operator` | 100.0% | none |
| `logs/agent/20260617-141235-479378` | `workspace/generated-operators` | N/A | not an artifact generation run |
| `logs/agent/20260617-141519-779916` | `workspace/rag-regression-broken/broken-config-operator` | 55.56% | operatorSpec, commandPlan, apiTypes, controller |

## Validation First Pass

| Log | make generate | make manifests | make test | e2e |
|---|---|---|---|---|
| `logs/agent/20260617-140047-627341` | not-measured | not-measured | not-measured | not-measured |
| `logs/agent/20260617-140801-334502` | succeeded | succeeded | succeeded | not-measured |
| `logs/agent/20260617-141235-479378` | not-measured | not-measured | not-measured | not-measured |
| `logs/agent/20260617-141519-779916` | failed | not-measured | not-measured | not-measured |

## Error Response

| Log | Failed Tool | Failed Step | Recovery Plan | Response Seconds |
|---|---|---|---|---:|
| `logs/agent/20260617-141519-779916` | validation | make generate | waiting-for-user-approval | 266.0 |
