# Kubebuilder Operator AI Agent

Kubebuilder 기반 Kubernetes Operator 개발을 자동화하기 위한 로컬 실행형 AI Agent 프로젝트입니다.

이 프로젝트는 단순히 AI에게 코드 작성을 질문하는 챗봇이 아니라, 자연어 요구사항 분석부터 Kubebuilder 개발 절차 안내, 산출물 생성, 검증 명령 실행, 실패 로그 분석, 수정 방향 제시까지 이어지는 생성·검증 중심 개발지원 시스템을 목표로 합니다.

## 과제명

Kubebuilder 기반 Operator 개발 자동화를 위한 AI 기반 생성·검증 시스템 구축

## 대상 사용자

- Kubebuilder 기반 Kubernetes Operator를 설계·개발하는 내부 개발자
- CRD, Controller, RBAC, Manifest, 테스트를 작성하는 플랫폼 엔지니어
- GitHub, Jenkins, Harbor, Argo CD 기반 개발·검증·배포 체계를 사용하는 조직

## 핵심 목표

- 자연어 요구사항을 Operator 개발 요구사항으로 구조화합니다.
- AI Agent가 Kubebuilder 개발 순서를 단계별로 안내합니다.
- CRD, Controller, RBAC, Manifest, 테스트 초안 등 필수 산출물 생성을 지원합니다.
- `make generate`, `make manifests`, `make test` 등 검증 명령 실행 흐름을 정의합니다.
- 실패 로그를 분석하여 원인과 해결 방향을 제시합니다.
- 필요 시 특정 산출물만 부분 수정하거나 재생성할 수 있는 구조를 지향합니다.
- GitHub, Jenkins, Harbor, Argo CD 연계까지 확장 가능한 구조로 설계합니다.

## 1차 MVP 범위

1차 MVP는 전체 자동화 시스템을 한 번에 구현하지 않고, 로컬 실행형 Agent 흐름을 검증하는 데 집중합니다.

- 현재 로컬 개발환경 점검
- `go`, `docker`, `kubectl`, `kind`, `helm`, `kubebuilder`, `kustomize`, `git` 설치 여부 확인
- Kubebuilder scaffold 생성 흐름 정리
- 예시 API 생성 흐름 정리
- CRD, Controller, RBAC, Manifest 생성 절차 문서화
- `make generate` 실행 및 결과 확인 흐름 정리
- `make manifests` 실행 및 결과 확인 흐름 정리
- `make test` 실행 및 결과 확인 흐름 정리
- 실패 로그 분석 기준 정리
- 프로젝트 목표, 아키텍처, 데모 시나리오, 개발 계획 문서화

## 디렉터리 구조

```text
C:\k8sagent
├── README.md
├── PROJECT_GOAL.md
├── ARCHITECTURE.md
├── DEMO_SCENARIO.md
├── DEVELOPMENT_PLAN.md
├── docs
├── agent
│   ├── prompts
│   ├── workflows
│   └── policies
├── scripts
├── examples
├── generated
├── logs
└── workspace
```

## 디렉터리 역할

| 경로 | 목적 |
| --- | --- |
| `docs` | 요구사항, Agent 흐름, 검증 흐름, 오류 대응 가이드 문서 |
| `agent/prompts` | 요구사항 분석, 생성, 검증 분석, 오류 진단용 프롬프트 초안 |
| `agent/workflows` | 환경 점검, scaffold 생성, generate/manifests/test 흐름 정의 |
| `agent/policies` | 명령 실행, 파일 수정, 부분 재생성 정책 |
| `scripts` | 이후 로컬 환경 점검 및 검증 실행 스크립트 위치 |
| `examples` | 샘플 Operator 요구사항 및 데모 입력 예시 |
| `profiles` | TrainingJob, RedisCache 등 Operator 예시 profile과 검증 규칙 |
| `generated` | Agent가 생성하는 중간 산출물 또는 스펙 저장 위치 |
| `logs` | 명령 실행 결과와 실패 로그 저장 위치 |
| `workspace` | 실제 Kubebuilder 프로젝트가 생성될 작업 공간 |

## Core Agent와 Profile 구조

이 프로젝트는 TrainingJob 전용 생성기가 아니라 Kubebuilder 기반 Operator 개발 절차를 자동화하는 범용 Agent 시스템입니다.

현재 구조는 다음 두 계층으로 나눕니다.

| 계층 | 역할 | 현재 예 |
| --- | --- | --- |
| Core Agent | Operator 종류와 무관한 공통 절차를 수행 | `spec_generator.py`, `command_planner.py`, `scaffold_runner.py` |
| Profile/Example | 특정 Operator 패턴의 sample, patch, e2e, warning 규칙을 정의 | `profiles/trainingjob.yaml`, `profiles/rediscache.yaml` |

TrainingJob은 GPU 학습 도메인을 대상으로 한 MVP 검증용 profile입니다. RedisCache는 StatefulSet/Service 기반 Operator로 확장하기 위한 예시 profile입니다.

현재 `artifact_patcher.py`, `e2e_runner.py`, `log_analyzer.py`에는 TrainingJob profile 로직이 일부 섞여 있습니다. 향후 리팩터링에서는 이 로직을 `profiles/` 또는 plugin 계층으로 분리하여 RedisCache와 다른 Operator profile도 같은 core pipeline을 재사용할 수 있게 합니다.

전체 파이프라인은 다음과 같습니다.

```text
requirement
  -> operator-spec.yaml
  -> command plan
  -> Kubebuilder scaffold
  -> artifact patch
  -> make generate/manifests/test
  -> kind e2e
  -> log analysis
```

리팩터링 계획은 [docs/refactoring-plan.md](docs/refactoring-plan.md)를 참고합니다.

## 시연 문서

현재 MVP 상태를 기준으로 심사/시연에서 사용할 수 있는 문서를 제공합니다.

- [TrainingJob 데모 시나리오](docs/demo-scenario-trainingjob.md)
- [발표자용 데모 스크립트](docs/demo-script.md)
- [현재 MVP 상태](docs/current-mvp-status.md)
- [데모 체크리스트](docs/demo-checklist.md)

## 현재 상태

현재 단계에서는 RedisCache Operator를 1차 MVP 샘플로 생성하고, 요구사항 구조화부터 Kubebuilder 산출물 확인, CRD 생성 검증, 기본 컴파일 검증까지 실행할 수 있는 데모 흐름을 제공합니다.

## RedisCache MVP 데모 실행

다음 명령으로 1차 MVP 흐름을 한 번에 확인할 수 있습니다.

```bash
./scripts/demo-rediscache-mvp.sh
```

이 스크립트는 다음을 확인합니다.

- 로컬 개발환경 점검
- `generated/rediscache-operator-spec.yaml` 구조화 스펙 확인
- `workspace/redis-cache-operator` Kubebuilder 산출물 확인
- `RedisCache` Spec/Status 타입 정의 확인
- `controller-gen` 기반 DeepCopy 및 CRD manifest 생성
- CRD schema에 `size`, `image`, `storageSize`, `phase`, `readyReplicas`, `message` 필드 포함 여부 확인
- `go test ./api/... ./cmd/... ./test/utils` 기본 컴파일 검증

실행 환경에 따라 Docker 권한 경고가 표시될 수 있습니다. 1차 MVP scaffold 검증은 Docker daemon 없이도 계속 진행되며, kind 클러스터 기반 e2e 검증 단계에서 Docker 연결이 필요합니다.

## Agent CLI 골격

자연어 요구사항을 구조화 스펙으로 변환하는 CLI 골격을 제공합니다.

범용 요구사항 템플릿을 기준으로 작성한 파일을 `operator-spec.yaml`로 변환할 수 있습니다.

```bash
cp requirements/template.txt requirements/my-operator.txt
# requirements/my-operator.txt 내용을 실제 Operator 요구사항으로 수정
python3 agent/tools/spec_generator.py requirements/my-operator.txt
```

기본 출력 경로는 다음 형식입니다.

```text
generated/<kind 소문자>-operator-spec.yaml
```

예를 들어 `kind`가 `TrainingJob`이면 `generated/trainingjob-operator-spec.yaml`이 생성됩니다. 변환 결과에는 `metadata`, `project`, `api`, `specFields`, `statusFields`, `controller`, `rbac`, `validation`, `warnings`, `errors`가 포함됩니다.

템플릿과 작성 가이드는 다음 문서를 참고합니다.

- [docs/operator-requirement-template.md](docs/operator-requirement-template.md)
- [docs/requirement-writing-guide.md](docs/requirement-writing-guide.md)
- [docs/spec-schema.md](docs/spec-schema.md)

생성된 스펙을 기준으로 Kubebuilder 실행 계획 문서를 만들 수 있습니다.

```bash
python3 agent/tools/command_planner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --output generated/trainingjob-command-plan.md
```

이 단계는 실제 명령을 실행하지 않고, `kubebuilder init`, `kubebuilder create api`, `make generate`, `make manifests`, `make test`를 어떤 순서와 목적으로 실행할지 Markdown 문서로 생성합니다.

계획을 검토한 뒤 scaffold runner로 실행 예정 명령을 확인할 수 있습니다. 기본 동작은 dry-run입니다.

```bash
python3 agent/tools/scaffold_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --workspace workspace/generated-operators \
  --dry-run
```

실제 실행 전에 로컬 도구, 스펙 필수값, 작업 디렉터리 상태를 preflight로 점검할 수 있습니다.

```bash
python3 agent/tools/scaffold_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --workspace workspace/generated-operators \
  --preflight
```

preflight 결과는 `logs/scaffold/<timestamp>/preflight.json`에 저장됩니다. 실패 항목이 있으면 `--execute` 실행 전 단계에서 중단합니다.

실제 Kubebuilder scaffold를 수행하려면 `--execute`를 명시합니다.

```bash
python3 agent/tools/scaffold_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --workspace workspace/generated-operators \
  --execute
```

대상 프로젝트 디렉터리가 이미 있으면 기본적으로 중단합니다. 기존 디렉터리를 삭제하고 다시 만들 때만 `--force`를 함께 사용합니다. 실제 실행 로그는 `logs/scaffold/<timestamp>/` 아래에 저장됩니다.

생성된 Kubebuilder 프로젝트에 스펙 필드, 샘플 CR, RBAC marker를 반영하려면 artifact patcher를 사용합니다. 기본 동작은 dry-run이며 수정 전후 diff만 출력합니다.

```bash
python3 agent/tools/artifact_patcher.py \
  --input generated/trainingjob-operator-spec.yaml \
  --project workspace/generated-operators/trainingjob-operator \
  --dry-run
```

TrainingJob profile의 sample 기본값을 사용하려면 `--profile`을 함께 전달합니다.

```bash
python3 agent/tools/artifact_patcher.py \
  --input generated/trainingjob-operator-spec.yaml \
  --project workspace/generated-operators/trainingjob-operator \
  --profile profiles/trainingjob.yaml \
  --dry-run
```

실제 파일 수정을 수행하려면 `--execute`를 명시합니다. `make generate`, `make manifests`, `make test`는 별도 검증 단계에서 실행합니다.

```bash
python3 agent/tools/artifact_patcher.py \
  --input generated/trainingjob-operator-spec.yaml \
  --project workspace/generated-operators/trainingjob-operator \
  --execute
```

실행 로그와 summary는 `logs/patch/<timestamp>/` 아래에 저장됩니다.

생성된 Operator가 실제 Kubernetes 클러스터에서 동작하는지 kind 기반 e2e runner로 확인할 수 있습니다. 기본 동작은 dry-run입니다.

```bash
python3 agent/tools/e2e_runner.py \
  --project workspace/generated-operators/trainingjob-operator \
  --cluster-name trainingjob-e2e \
  --sample workspace/generated-operators/trainingjob-operator/config/samples/ml_v1alpha1_trainingjob.yaml \
  --dry-run
```

실제 kind 클러스터와 kubectl 명령을 사용하려면 `--execute`를 명시합니다.

```bash
python3 agent/tools/e2e_runner.py \
  --project workspace/generated-operators/trainingjob-operator \
  --cluster-name trainingjob-e2e \
  --sample workspace/generated-operators/trainingjob-operator/config/samples/ml_v1alpha1_trainingjob.yaml \
  --execute
```

기존 sample 리소스를 지우고 새 Job spec을 깨끗하게 검증하려면 `--clean`을 함께 사용합니다. 기본적으로 PVC는 유지하며, PVC까지 삭제하려면 `--delete-pvc`를 추가합니다.

```bash
python3 agent/tools/e2e_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --clean \
  --dry-run
```

```bash
python3 agent/tools/e2e_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --clean \
  --execute
```

TrainingJob profile 값을 명시적으로 사용하려면 `--profile`을 함께 전달합니다.

```bash
python3 agent/tools/e2e_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --profile profiles/trainingjob.yaml \
  --clean \
  --dry-run
```

e2e 로그와 summary는 `logs/e2e/<timestamp>/` 아래에 저장됩니다.

저장된 scaffold, patch, e2e 로그는 log analyzer로 요약할 수 있습니다. analyzer는 `summary.json`을 먼저 읽고, 실패 단계가 있으면 해당 stdout/stderr 로그를 함께 확인하여 실패 원인과 수정 방향을 Markdown으로 생성합니다.

```bash
python3 agent/tools/log_analyzer.py \
  --log-dir logs/e2e/20260607-213346
```

분석 결과는 기본적으로 입력한 로그 디렉터리의 `analysis.md`에 저장됩니다. 예를 들어 e2e 성공 로그라면 전체 실행 결과, warning, Job spec validation 결과, summary 기반 재실행 권장 명령을 요약합니다. 실패 로그라면 `failedStep`, 관련 명령, 오류 유형, 근거 로그, 해결 방향을 함께 정리합니다.

초보자용 대화형 입력:

```bash
./scripts/agent-requirement-cli.py interactive \
  -o generated/training-job-operator-spec.yaml \
  --print-commands
```

대화형 모드는 다음 순서로 질문합니다.

- 관리하려는 대상
- Custom Resource 이름
- domain, group, version
- 사용자가 입력할 값
- 사용자가 보고 싶은 상태
- Operator가 생성/관리할 Kubernetes 리소스
- 입력값과 생성 리소스의 매핑
- status 갱신 기준

파일 기반 입력:

```bash
./scripts/agent-requirement-cli.py \
  -i examples/rediscache-requirement.txt \
  -o generated/redis-cache-operator-spec.yaml \
  --print-commands
```

이 CLI는 입력 요구사항에서 `domain`, `group`, `version`, `kind`, `spec`, `status`, `controller` 정보를 추출하여 YAML 스펙을 생성하고, 실행할 Kubebuilder 명령 후보를 출력합니다.

생성 결과 예:

```text
generated/redis-cache-operator-spec.yaml
```

현재 CLI는 LLM을 붙이기 전의 MVP 골격이며, 명시적으로 작성된 요구사항 문장을 규칙 기반으로 파싱합니다. 이후 단계에서 LLM 기반 Semantic Parsing, RAG 검색, 검증 로그 분석 Agent와 연결할 수 있습니다.

## LangChain 기반 Agent Orchestrator

기존 CLI 도구 위에 LangChain-style Agent Orchestrator를 추가했습니다.

본 시스템은 LLM planner 기반 Agent 구조를 사용합니다. Agent는 요구사항을 요약하고, `knowledge-base` 문서를 검색한 뒤, LLM planner가 실행 계획을 JSON으로 생성하고, 기존 CLI 도구를 Tool wrapper로 호출합니다.

RAG는 현재 로컬 Markdown `knowledge-base` 검색으로 구현되어 있습니다. Vector DB와 Reranker는 이후 확장 지점입니다.

MVP는 안전을 위해 기본 dry-run 중심입니다. 실제 scaffold, patch, e2e 실행은 별도 `--execute`가 명시될 때만 수행합니다.

LLM planner를 사용하려면 선택 의존성과 OpenAI API key가 필요합니다. `OPENAI_API_KEY`가 없거나 LLM 호출이 실패하면 다른 planner로 대체하지 않고 명확한 오류를 출력합니다.

```bash
pip install -r requirements.txt
export OPENAI_API_KEY=<your-api-key>
export OPENAI_MODEL=gpt-5.4-mini
```

`OPENAI_MODEL`을 지정하지 않으면 기본값은 `gpt-5.4-mini`입니다. 빠른 반복 테스트나 비용/지연 최적화가 필요하면 `OPENAI_MODEL=gpt-4.1-mini`처럼 더 작은 모델로 바꿔 실행할 수 있습니다.

대표 실행 예시 1: requirement 기반 dry-run

```bash
python3 agent/langchain_agent.py \
  --requirement requirements/appconfig.txt \
  --profile profiles/appconfig.yaml \
  --mode dry-run
```

Agent 실행 결과에는 다음 항목이 포함됩니다.

- Requirement Summary
- Missing Information Check
- Retrieved Knowledge
- LLM Planner Output
- AI Reasoning
- RAG Evidence Used By LLM
- Tool Call Plan From LLM
- Selected Profile
- Tool Execution Results
- Generated Files
- Warnings / Errors
- Next Recommended Actions

특히 `RAG Evidence Used By LLM` 섹션은 검색된 문서가 어떤 판단에 사용되었는지 보여줍니다. 예를 들어 `rbac-marker.md`가 RBAC 권한 추론에 사용되었는지, `reconcile-pattern.md`가 Controller 동작 계획에 사용되었는지 확인할 수 있습니다.

기본은 dry-run이며, 실제 scaffold, patch, e2e 변경 작업은 `--execute`가 명시되지 않으면 수행하지 않습니다. 실행 결과는 `logs/agent/<timestamp>/summary.json`과 `logs/agent/<timestamp>/agent-report.md`에 저장됩니다.

실제 LLM 연결 여부는 다음 파일로 확인합니다.

```bash
ls -al logs/agent
cat logs/agent/<timestamp>/llm-output.json
cat logs/agent/<timestamp>/agent-report.md
```

`llm-output.json`에는 모델이 생성한 요구사항 요약, 누락 정보, RAG 근거, Tool 호출 계획이 저장됩니다. 이 파일이 심사에서 “모델이 실제로 판단했다”는 핵심 증거입니다.

대표 실행 예시 2: log 분석 기반 AI 판단

기존 실행 로그를 Agent가 다시 분석하게 할 수도 있습니다. 이 모드는 `log_analyzer.py` 결과와 `knowledge-base`의 troubleshooting 문서를 함께 참조해 성공/실패 판단, warning 해석, 다음 조치 방향을 설명합니다.

```bash
python3 agent/langchain_agent.py \
  --analyze-log logs/e2e/20260607-213346
```

TrainingJob e2e 로그의 GPU Pending 케이스는 `succeeded-with-warning`으로 분류됩니다. Controller가 Job을 생성하지 못한 오류가 아니라, kind 클러스터에 `nvidia.com/gpu` 리소스가 없어 Pod가 Pending 상태로 남은 케이스이기 때문입니다.

이 모드에서 LLM은 `summary.json`, `analysis.md`, troubleshooting RAG 문서를 함께 읽고 다음 JSON 판단을 생성합니다.

```json
{
  "decision": "succeeded | failed | succeeded-with-warning",
  "classification": "...",
  "rootCause": "...",
  "evidence": [],
  "ragEvidence": [],
  "recommendedFixes": [],
  "rerunCommand": "...",
  "explanationForBeginner": "..."
}
```

아키텍처 설명은 [docs/ai-agent-architecture.md](docs/ai-agent-architecture.md)를 참고합니다.

## Web UI

CLI는 실제 자동화 core이고, Web UI는 초보자 입력과 심사용 시연을 위한 얇은 wrapper입니다. Web UI도 내부적으로 `agent/langchain_agent.py`를 호출하므로 CLI와 같은 Agent 파이프라인을 사용합니다.

의존성 없이 실행하는 기본 Web UI:

```bash
python3 web/server.py 8000
```

브라우저에서 접속:

```text
http://localhost:8000
```

FastAPI 기반 Web UI를 사용하려면 선택 의존성을 설치한 뒤 실행합니다.

```bash
pip install -r requirements.txt

uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Web UI에서 할 수 있는 작업:

- 자연어 requirement 기반 Agent dry-run
- AppConfig, RedisCache, TrainingJob profile 선택
- LLM planner 기반 실행
- 기존 e2e 로그 분석
- Agent report, stdout, stderr 확인

안전을 위해 Web UI는 실제 scaffold/e2e `--execute` 버튼을 제공하지 않습니다. 실제 변경 작업은 CLI에서 명시적으로 `--execute`를 사용할 때만 수행합니다.

## 스펙 기반 Kubebuilder Scaffold

구조화 스펙 YAML을 기반으로 Kubebuilder 프로젝트를 생성할 수 있습니다.

```bash
./scripts/scaffold-from-spec.py generated/training-job-operator-spec.yaml
```

기존 workspace를 다시 만들려면:

```bash
./scripts/scaffold-from-spec.py generated/training-job-operator-spec.yaml --force
```

이 스크립트는 다음을 수행합니다.

- `kubebuilder init`
- `kubebuilder create api`
- `api/<version>/*_types.go`에 spec/status 필드 반영
- `config/samples` 샘플 Custom Resource 갱신
- `make generate`
- `make manifests`

생성 결과 예:

```text
workspace/training-job-operator
```

## WSL 개발환경

시스템 패키지 설치 권한이 없는 WSL 환경에서는 프로젝트 로컬 도구 설치 스크립트를 사용합니다.

```bash
./scripts/install-local-tools.sh
./scripts/check-env.sh
```

설치된 로컬 도구는 `.tools/bin` 아래에 위치합니다. 현재 셸에서 바로 사용하려면 다음을 실행합니다.

```bash
export PATH="/home/ch0618/k8sagent/.tools/bin:$PATH"
```

자세한 내용은 [docs/development-environment.md](docs/development-environment.md)를 참고합니다.
