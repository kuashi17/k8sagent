# Local Model Usage Policy

## 목적

이 프로젝트는 오프라인 또는 내부망 환경에서도 사용할 수 있는 Kubebuilder Operator 개발 Agent를 목표로 한다.

LLM은 외부 API가 아니라 Ollama 기반 local provider만 사용한다. 모델은 모든 작업을 직접 수행하는 실행자가 아니라, 요구사항 해석과 판단을 돕는 계획 엔진으로 사용한다.

## 역할 분리

```text
Local LLM
  -> 요구사항 요약
  -> 누락 정보 판단
  -> RAG 문서 근거 연결
  -> Tool 호출 계획 생성
  -> 로그 분석 및 recovery plan 초안 생성

Policy / Rule layer
  -> Tool allowlist 검증
  -> workspace path 검증
  -> --execute gate 검증
  -> make target allowlist 검증
  -> recovery 자동 실행 차단

Tool wrapper
  -> 실제 spec 생성
  -> Kubebuilder scaffold
  -> artifact patch
  -> make 검증
  -> kind 검증
```

## 모델 선택 기준

CPU 환경에서는 모델 크기와 응답 시간이 직접적인 개발 생산성에 영향을 준다.

| 모델 예시 | 용도 | 비고 |
|---|---|---|
| `qwen2.5-coder:1.5b` | 빠른 실험, dry-run 계획 검증 | 품질보다 속도 우선 |
| `qwen2.5-coder:3b` | 기본 개발 모델 | 현재 기본값 |
| `qwen2.5-coder:7b` | 최종 분석, 품질 우선 검증 | CPU에서는 시간이 오래 걸릴 수 있음 |

현재 기본값:

```bash
export LOCAL_LLM_BASE_URL=http://localhost:11434/v1
export LOCAL_LLM_MODEL=qwen2.5-coder:3b
```

## Run Level

Agent는 실행 깊이를 나누어 CPU 환경에서도 사용할 수 있게 한다.

| run-level | LLM planning | Tool 실행 | final LLM evaluation | 용도 |
|---|---|---|---|---|
| `fast` | 수행 | 수행 | 생략 | 개발 중 빠른 피드백 |
| `standard` | 수행 | 수행 | 수행 | 기본 검증 |
| `full` | 수행 | 수행 | 수행 | 향후 kind/e2e/reliability 포함용 |

예시:

```bash
python3 agent/langchain_agent.py \
  --requirement requirements/appconfig.txt \
  --profile profiles/appconfig.yaml \
  --mode dry-run \
  --run-level fast
```

## Cache 정책

같은 requirement, profile, RAG 문서, local model 조합은 동일한 LLM planning 결과를 재사용할 수 있다.

기본적으로 requirement planning cache는 활성화된다.

```text
.cache/agent/llm-plans/<hash>.json
```

제어 옵션:

```bash
--no-cache       # cache 사용 안 함
--refresh-cache  # 기존 cache 무시하고 새 LLM planning 결과 저장
```

캐시는 다음 입력을 기준으로 계산한다.

- requirement text
- selected RAG documents
- profile summary
- safety mode
- local LLM base URL
- local LLM model
- cache schema version

## 안전 원칙

- LLM은 직접 `kubectl`, `make`, `docker`, `kind`, shell command를 실행하지 않는다.
- LLM은 Tool 호출 계획만 생성한다.
- 실제 실행은 Tool wrapper가 담당한다.
- Tool wrapper는 allowlist와 인자 검증을 통과해야 한다.
- `--execute`가 없으면 변경 Tool은 dry-run으로 강제된다.
- recovery Tool은 항상 사용자 승인 전에는 실행되지 않는다.

## 확인 파일

Agent 실행 후 다음 파일로 모델 사용과 성능을 확인한다.

| 파일 | 설명 |
|---|---|
| `llm-input.json` | LLM에 전달된 입력 |
| `llm-output.json` | LLM이 생성한 계획 |
| `llm-raw-output.txt` | 모델 원문 응답 |
| `planner-cache.json` | cache hit/path 정보 |
| `timings.json` | RAG, LLM planning, Tool 실행, final evaluation 소요 시간 |
| `safety-evaluation.json` | Tool 실행 안전 정책 평가 |
| `evidence-trace.json` | RAG/LLM/Tool 근거 흐름 |
