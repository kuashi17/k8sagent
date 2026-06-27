# Demo Script

## 오프닝

오늘 시연할 시스템은 Kubebuilder 기반 Kubernetes Operator 개발을 자동화하기 위한 로컬 실행형 AI Agent MVP입니다.

핵심은 단순히 AI에게 "Operator 코드를 작성해줘"라고 묻는 것이 아닙니다. 자연어 요구사항을 구조화 스펙으로 바꾸고, Kubebuilder 명령 계획을 만들고, 실제 scaffold와 검증 명령을 실행하며, 결과 로그까지 분석하는 개발지원 흐름을 만드는 것입니다.

## 단순 AI 질의와 로컬 실행형 Agent의 차이

일반적인 AI 질의는 답변 텍스트를 생성하는 데서 끝납니다.

이 Agent는 로컬 프로젝트 안에서 다음 작업을 이어서 수행합니다.

- 요구사항 파일을 읽습니다.
- `operator-spec.yaml`을 생성합니다.
- Kubebuilder 실행 계획을 문서화합니다.
- 실제 scaffold를 수행합니다.
- API 타입, sample YAML, RBAC marker를 보정합니다.
- `make generate`, `make manifests`, `make test`를 실행합니다.
- kind 클러스터에서 e2e를 수행합니다.
- 로그와 summary를 저장하고 분석 리포트를 생성합니다.

즉, 답변 생성이 아니라 개발 절차의 생성·검증·분석을 연결하는 것이 목표입니다.

## TrainingJob profile 설명

이번 시연에서 사용하는 TrainingJob은 GPU 학습 작업을 Kubernetes Job으로 실행하는 예시 profile입니다.

중요한 점은 이 시스템이 TrainingJob 전용 생성기가 아니라는 것입니다. TrainingJob은 MVP 검증을 위한 profile이고, core Agent는 Kubebuilder 기반 Operator 개발 절차를 범용으로 자동화하도록 설계되어 있습니다.

동일한 구조로 RedisCache처럼 StatefulSet과 Service를 관리하는 Operator profile도 확장할 수 있습니다.

## 시연 흐름 설명

먼저 사용자의 자연어 요구사항을 확인합니다.

이 요구사항에는 `domain`, `group`, `version`, `kind`, spec 필드, status 필드, Controller 책임이 포함되어 있습니다.

다음으로 `spec_generator.py`가 요구사항을 읽고 `operator-spec.yaml`을 생성합니다. 이 파일은 이후 모든 단계가 공유하는 내부 계약입니다.

그 다음 `command_planner.py`가 Kubebuilder 실행 계획을 Markdown으로 생성합니다. 이 단계에서는 아직 명령을 실행하지 않고, 사람이 검토할 수 있는 계획을 보여줍니다.

이후 `scaffold_runner.py`를 dry-run으로 실행하여 실제 생성 전에 어떤 명령이 수행될지 확인합니다. 문제가 없으면 execute 모드로 Kubebuilder scaffold를 생성합니다.

scaffold가 생성되면 `artifact_patcher.py`가 스펙을 기준으로 API 타입, sample YAML, RBAC marker를 보정하고 `make generate`, `make manifests`, `make test`를 실행합니다.

마지막으로 `e2e_runner.py`가 kind 클러스터에서 clean e2e를 실행합니다. 기존 테스트 리소스를 삭제하고, CRD를 설치하고, Controller를 실행하고, sample TrainingJob을 생성한 뒤 Kubernetes Job이 생성되는지 확인합니다.

## clean e2e 성공 결과 설명

현재 clean e2e는 다음 로그에서 성공 결과를 확인할 수 있습니다.

```text
logs/e2e/20260607-213346/summary.json
```

검증 결과는 다음과 같습니다.

- kind 클러스터 확인 성공
- CRD 설치 성공
- TrainingJob CR 생성 성공
- Kubernetes Job 생성 성공
- Job spec validation 성공
- TrainingJob status 갱신 확인
- failedStep 없음

Job spec validation에서는 사용자가 입력한 spec 값이 실제 Job에 반영됐는지 확인했습니다.

- `spec.image`가 Job container image로 반영됨
- `spec.gpuCount`가 `nvidia.com/gpu` limit으로 반영됨
- `spec.pvcName`이 PVC claimName으로 반영됨
- `/workspace` volumeMount가 존재함
- `DATASET_PATH`, `OUTPUT_PATH` 환경변수가 반영됨

## GPU 부족 Pending을 warning으로 분류한 이유

kind 클러스터는 일반적으로 GPU 리소스를 제공하지 않습니다.

따라서 `gpuCount: 1`을 요청한 Pod는 `Insufficient nvidia.com/gpu` 때문에 Pending 상태가 될 수 있습니다.

이번 e2e의 목적은 Pod가 실제 학습을 완료하는지 확인하는 것이 아니라, Controller가 TrainingJob spec을 읽고 올바른 Kubernetes Job을 생성했는지 확인하는 것입니다.

그래서 Job spec validation이 성공하고 Pending 원인이 GPU 부족이면 실패가 아니라 warning으로 기록합니다.

이 warning은 `log_analyzer.py`가 `succeeded-with-warning`으로 요약합니다.

## 로그 분석 설명

마지막 단계에서 `log_analyzer.py`를 실행합니다.

```bash
python3 agent/tools/log_analyzer.py \
  --log-dir logs/e2e/20260607-213346
```

분석 결과는 다음 파일에 저장됩니다.

```text
logs/e2e/20260607-213346/analysis.md
```

이 리포트는 전체 실행 결과, 실패 단계 여부, warning, Job spec validation, 재실행 권장 명령을 정리합니다.

## AI 기술이 드러나는 부분

이제 시연에서는 기존 자동화 CLI 위에 LangChain Agent 계층이 올라간 모습을 함께 보여줍니다.

발표 멘트:

"여기서 중요한 점은 단순히 Python 스크립트를 순서대로 실행하는 것이 아니라는 점입니다. LangChain Agent가 요구사항이나 로그를 입력으로 받고, 관련 문서를 RAG로 검색한 뒤, 기존 자동화 도구를 Tool로 호출합니다."

"심사 시연의 planner는 `llm`입니다. LLM planner는 RAG 검색 결과를 입력으로 받아 요구사항 해석, 부족 정보 판단, 실행 계획 생성, 로그 분석 설명을 JSON으로 만듭니다. API key나 모델 설정이 없으면 다른 planner로 대체하지 않고 명확한 오류를 출력합니다."

"RAG는 현재 Vector DB 대신 로컬 Markdown `knowledge-base` 검색으로 구현했습니다. Kubebuilder 기본 흐름, RBAC marker, Reconcile 패턴, troubleshooting 문서를 검색하고, Agent가 그 결과를 판단 근거로 사용합니다."

"로그 분석 시연에서는 TrainingJob e2e 성공 로그를 입력합니다. Agent는 먼저 `log_analyzer.py` Tool을 호출하고, 생성된 `analysis.md`와 `summary.json`을 읽습니다. 그 다음 troubleshooting 문서와 TrainingJob 예시 문서를 검색해 GPU Pending warning을 해석합니다."

실행 명령:

```bash
python3 agent/langchain_agent.py \
  --analyze-log logs/e2e/20260607-213346 \
  --planner llm
```

설명 포인트:

- Agent는 `failedStep=None`이므로 실행 실패가 아니라고 판단합니다.
- `jobSpecValidation.passed=True`이므로 Controller가 만든 Job spec은 요구사항을 만족한다고 봅니다.
- Pod Pending은 Controller 오류가 아니라 kind 클러스터에 `nvidia.com/gpu` 리소스가 없어서 발생한 scheduling warning입니다.
- 따라서 결과를 `succeeded-with-warning`으로 분류합니다.
- 다음 조치로 GPU 노드가 있는 클러스터에서 실행하거나 `gpuCount: 0` e2e sample을 사용하라고 제안합니다.

안전장치 설명:

- 현재 MVP는 기본적으로 dry-run 중심입니다.
- 실제 scaffold, patch, e2e 실행은 `--execute`가 명시될 때만 수행합니다.
- 심사 시에는 먼저 dry-run과 로그 분석을 보여주고, 실제 실행은 검증된 명령으로만 진행합니다.

## 향후 확장 계획

범용 lifecycle은 공통 kind runner와 validator로 분리되었고, legacy Job e2e는
명시적인 `job-workload-v1` profile 계약으로 격리되었습니다.

우선순위는 다음과 같습니다.

다음 우선순위는 다음과 같습니다.

1. `artifact_patcher.py`에 남은 profile hook 정리
2. `log_analyzer.py`의 domain-specific warning/evidence plugin화
3. legacy e2e 호출을 공통 kind validator로 완전히 이관

이후 Jenkins와 연계하면 `make generate`, `make manifests`, `make test`, e2e 결과를 CI에서 수집할 수 있습니다.

Harbor 연계를 통해 Operator 이미지 빌드와 푸시 결과를 확인할 수 있습니다.

Argo CD 연계를 통해 배포 반영 상태와 Sync/Health 상태를 확인할 수 있습니다.

최종적으로는 요구사항 입력부터 생성, 검증, 오류 분석, 수정 제안, 배포 확인까지 이어지는 Operator 개발 자동화 Agent로 확장하는 것이 목표입니다.
