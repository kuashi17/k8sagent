# MVP Evaluation

## 목적

MVP Evaluation은 제출 계획서의 평가 지표를 실제 Agent 실행 로그로 계산한다.

측정 대상 지표는 다음 네 가지다.

1. 개발 단계별 작업 시간 단축
2. 필수 산출물 생성 완성도
3. 검증 단계 1차 통과율
4. 오류 대응 지원 속도

평가는 `logs/agent/<timestamp>` 아래에 저장된 Agent 실행 결과를 읽고, `evaluation/results/mvp/<timestamp>`에 JSON과 Markdown 리포트를 생성한다.

## Baseline

기존 수작업 기준 시간은 `evaluation/mvp-baseline.yaml`에서 관리한다.

```yaml
manualBaseline:
  requirementToArtifactsMinutes: 120
  source: "placeholder: 기존 수작업 수행 기준 또는 사전 측정값으로 교체 필요"
  measured: false
```

`measured: false`이면 작업 시간 단축률은 임의 계산하지 않고 `측정 불가`로 표시한다. 실제 수작업 측정값이 준비되면 `source`와 `measured`를 갱신한다.

## 실행 방법

대표 4개 로그만 평가:

```bash
python3 agent/evaluation/mvp_evaluator.py \
  --log-paths \
    logs/agent/20260617-140047-627341 \
    logs/agent/20260617-140801-334502 \
    logs/agent/20260617-141235-479378 \
    logs/agent/20260617-141519-779916 \
  --baseline evaluation/mvp-baseline.yaml \
  --output-dir evaluation/results/mvp
```

전체 Agent 로그 평가:

```bash
python3 agent/evaluation/mvp_evaluator.py \
  --logs-dir logs/agent \
  --baseline evaluation/mvp-baseline.yaml \
  --output-dir evaluation/results/mvp
```

스크립트 wrapper:

```bash
./scripts/evaluate-mvp.sh --log-paths \
  logs/agent/20260617-140047-627341 \
  logs/agent/20260617-140801-334502 \
  logs/agent/20260617-141235-479378 \
  logs/agent/20260617-141519-779916
```

## 산출물

`evaluation/results/mvp/<timestamp>/` 아래에 다음 파일이 생성된다.

- `mvp-evaluation-summary.json`
- `mvp-evaluation-details.json`
- `artifact-completion-results.json`
- `validation-pass-results.json`
- `error-response-results.json`
- `mvp-evaluation-report.md`

## 지표 계산 방식

### 작업 시간 단축

`requirement-planning` + `agentMode=execute` 로그의 실행 시간을 사용한다.

기존 로그에는 별도 `startedAt`이 없으므로 로그 디렉터리 이름을 시작 시각으로, `summary.createdAt`을 종료 시각으로 사용한다.

baseline이 실제 측정값으로 표시되지 않으면 `측정 불가`로 처리한다.

### 산출물 완성도

`requirement-planning` + `agentMode=execute` 로그만 요약 지표에 포함한다.

필수 산출물:

- `operator-spec.yaml`
- `command-plan.md`
- API type Go file
- Controller file
- CRD manifest
- RBAC manifest
- sample Custom Resource
- Makefile
- test directory 또는 make test 결과

검사는 파일 존재와 최소 유효성으로 나눈다. YAML은 parse 가능해야 하고, CRD/RBAC/sample은 최소 필드를 확인한다.

### 1차 검증 통과율

`tool-results.json`의 validation Tool 첫 실행 결과를 기준으로 계산한다.

대상:

- `make generate`
- `make manifests`
- `make test`
- `build`
- `e2e`

재실행 성공은 최초 성공으로 계산하지 않는다.

### 오류 대응 속도

실패 로그에서 `failure-context.json`과 `validated-recovery-plan.json`이 있는지 확인한다.

현재 기존 로그는 실패 시점과 recovery plan 생성 시점의 개별 timestamp를 저장하지 않으므로, Agent 전체 실행 시간을 failure-to-recovery 응답 시간의 상한값으로 사용한다.

향후 Agent가 per-event timestamp를 저장하면 더 정확한 계산으로 교체할 수 있다.

## 주의사항

- 측정 데이터가 부족하면 임의로 성공 처리하지 않는다.
- log-analysis 로그는 산출물 완성도 요약 지표에서 제외한다.
- dry-run 로그는 추적용으로 표시하지만, full artifact completion 요약에는 포함하지 않는다.
- 실패 로그는 산출물 완성도와 1차 통과율에 실패로 반영된다.
