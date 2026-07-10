# Evaluation Metrics

이 문서는 Agent 실행 로그를 바탕으로 제품의 품질과 성과 지표를 계산하는 방법을 설명합니다.

## 측정 대상

측정 대상 지표는 다음 네 가지입니다.

1. 요구사항 입력부터 주요 산출물 생성까지의 소요 시간
2. 필수 산출물 생성 완성도
3. 검증 단계 1차 통과율
4. 오류 발생 후 원인과 다음 조치 제시까지의 시간

## Baseline

기존 수작업 기준 시간은 `evaluation/mvp-baseline.yaml`에서 관리합니다.

```yaml
manualBaseline:
  requirementToArtifactsMinutes: 120
  source: "placeholder: 기존 수작업 수행 기준 또는 사전 측정값으로 교체 필요"
  measured: false
```

`measured: false`이면 작업 시간 단축률은 임의 계산하지 않고 `측정 불가`로 표시합니다.
실제 수작업 측정값이 준비되면 `source`와 `measured`를 갱신합니다.

## 실행 방법

대표 Agent 로그만 평가:

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

`evaluation/results/mvp/<timestamp>/` 아래에 다음 파일이 생성됩니다.

- `mvp-evaluation-summary.json`
- `mvp-evaluation-details.json`
- `artifact-completion-results.json`
- `validation-pass-results.json`
- `error-response-results.json`
- `mvp-evaluation-report.md`

## 지표 계산 방식

### 작업 시간 단축

`requirement-planning` + `agentMode=execute` 로그의 실행 시간을 사용합니다.

기존 로그에는 별도 `startedAt`이 없으므로 로그 디렉터리 이름을 시작 시각으로,
`summary.createdAt`을 종료 시각으로 사용합니다.

### 산출물 완성도

Operator spec, command plan, Kubebuilder workspace, generated API type,
RBAC manifest, validation summary 등 필수 산출물의 존재 여부를 확인합니다.

### 검증 통과율

`make generate`, `make manifests`, `make test` 결과를 읽어 1차 통과 여부를 계산합니다.

### 오류 대응 시간

실패 로그가 생성된 시각부터 구조화 errorCode, 사용자 메시지, 다음 조치가 생성된 시각까지를 측정합니다.
