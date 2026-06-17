# Generic Agent Core

## 핵심 방향

이 프로젝트는 AppConfig, TrainingJob, RedisCache 같은 특정 Operator 생성기가 아니다.

목표는 사용자가 어떤 Operator를 만들고 싶은지 자연어로 말하면, Agent가 다음을 수행하는 것이다.

1. 사용자의 의도와 부족 정보를 파악한다.
2. RAG로 관련 Kubebuilder, RBAC, Reconcile, troubleshooting 문서를 찾는다.
3. Local LLM planner가 실행 계획과 Tool 호출 계획을 만든다.
4. Tool allowlist와 안전 정책으로 계획을 검증한다.
5. 기존 CLI Tool을 dry-run 또는 execute 모드로 안전하게 실행한다.
6. 실행 결과를 다시 LLM이 평가하고 다음 조치를 설명한다.

## AppConfig의 위치

`requirements/appconfig.txt`와 `profiles/appconfig.yaml`은 사용자에게 고정된 기준을 제시하기 위한 것이 아니다.

AppConfig는 다음 목적의 내부 fixture다.

- Agent dry-run 회귀 검증
- Tool allowlist와 execute gate 검증
- kind 클러스터 lifecycle 검증
- ConfigMap 생성, update, disabled, delete, restore 같은 단순하고 빠른 Kubernetes 동작 확인
- Local LLM planning cache와 응답 시간 검증

즉, AppConfig는 제품 컨셉이 아니라 테스트 표본이다.

## Profile의 역할

profile은 사용자의 요구사항을 대체하지 않는다.

profile의 역할은 다음과 같다.

- 유사 패턴의 sample 기본값 제공
- e2e 검증 규칙 제공
- 특정 workload의 warning 해석 규칙 제공
- 반복 테스트 fixture 정의

Agent는 profile을 `hint-only`로 취급한다. Operator의 kind, spec/status field, controller 책임, 관리 리소스는 현재 requirement text가 우선한다.

## Requirement Analyzer

`agent/requirement_analyzer.py`는 LLM 호출 전에 가벼운 분석을 수행한다.

- primary intent 추정
- managed resource hint 추정
- profile 후보 순위 계산
- 명시 profile과 자동 후보를 구분

이 분석 결과는 LLM 입력과 `agent-report.md`에 포함된다. 따라서 사용자는 Agent가 어떤 의도로 요구사항을 해석했는지 확인할 수 있다.

## 사용자가 편하게 쓰는 방식

대충 쓴 문장을 requirement 파일로 정리:

```bash
python3 agent/requirement_builder.py \
  --draft "웹 애플리케이션 이미지를 Deployment와 Service로 배포하는 Operator를 만들고 싶어" \
  --output requirements/web-service.txt \
  --assume-defaults \
  --print-questions
```

가장 단순한 사용 방식:

```bash
python3 agent/langchain_agent.py \
  --requirement requirements/my-operator.txt \
  --mode dry-run
```

유사한 profile hint를 주고 싶을 때:

```bash
python3 agent/langchain_agent.py \
  --requirement requirements/my-operator.txt \
  --profile profiles/trainingjob.yaml \
  --mode dry-run
```

실제 생성까지 진행할 때:

```bash
python3 agent/langchain_agent.py \
  --requirement requirements/my-operator.txt \
  --mode execute \
  --execute
```

초보자에게는 CLI만으로는 어렵기 때문에 Web UI에서는 다음 흐름을 제공하는 것이 적합하다.

- 큰 입력창에 “만들고 싶은 Operator”를 자연어로 작성
- Agent가 부족 정보를 표시
- 필요하면 추가 질문 목록 제시
- dry-run 결과를 먼저 보여줌
- 생성될 파일과 실행될 명령을 사람이 확인
- execute는 CLI 또는 승인된 내부 UI에서만 허용

## Generic Validation Boundary

모든 Operator에 대해 kind e2e를 자동으로 일반화하는 것은 현재 범위가 아니다.

현재 범용 core가 책임지는 검증:

- requirement 분석
- RAG 검색
- LLM Tool 계획
- spec 생성
- command plan 생성
- scaffold dry-run/execute
- artifact patch
- `make generate`
- `make manifests`
- `make test`
- 실패 시 recovery plan 생성

profile 또는 fixture가 있을 때만 수행하는 검증:

- kind e2e
- 특정 하위 리소스 spec validation
- workload-specific warning 해석
- lifecycle 검증

이 경계를 유지하면 시스템이 특정 예시에 묶이지 않으면서도, 준비된 profile에 대해서는 더 깊은 검증을 제공할 수 있다.

## Profile-less Regression Fixtures

다음 요구사항은 profile 없이 Agent core가 동작하는지 확인하기 위한 회귀 테스트다.

- `requirements/secret-sync.txt`: Secret 관리 Operator
- `requirements/scheduled-task.txt`: CronJob 기반 Operator
- `requirements/web-service.txt`: Deployment/Service 기반 Operator

검증 명령:

```bash
python3 agent/evaluation/profileless_requirement_runner.py \
  --output-dir evaluation/results/profileless/generic-check \
  --run-level fast
```

## 보고서에서 확인할 것

`logs/agent/<timestamp>/agent-report.md`에서 다음 섹션을 확인한다.

- `Requirement Intent`: Agent가 사용자의 의도를 어떻게 분류했는지
- `Missing Information Check`: 부족한 요구사항
- `Profile Hint`: profile이 고정 기준이 아니라 hint로 사용됐는지
- `RAG Evidence Used By LLM`: 어떤 문서를 근거로 판단했는지
- `Tool Call Validation`: 허용된 Tool과 거부된 Tool
- `Safety Evaluation`: dry-run/execute gate, 경로 제한, allowlist

이 구조가 유지되면 특정 예시에 종속되지 않고, 사용자가 어떤 Operator 요구사항을 입력해도 Agent가 같은 core 흐름으로 대응할 수 있다.
