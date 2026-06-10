# TrainingJob Demo Scenario

## 데모 목적

이 문서는 현재 구현된 로컬 MVP를 기준으로 심사/시연에서 보여줄 수 있는 TrainingJob Operator 생성·검증 흐름을 정리합니다.

TrainingJob은 GPU 학습 도메인을 대상으로 한 MVP 검증용 profile/example입니다. 이 프로젝트의 목적은 TrainingJob 전용 생성기가 아니라 Kubebuilder 기반 Operator 개발 절차를 자동화하는 범용 Agent core를 만드는 것입니다.

## 전체 시연 흐름

1. 자연어 요구사항 확인
2. `operator-spec.yaml` 생성
3. command plan 생성
4. scaffold dry-run
5. scaffold execute
6. artifact patch
7. `make generate`, `make manifests`, `make test`
8. clean e2e 실행
9. Job spec validation 확인
10. `log_analyzer.py`로 성공/경고 분석
11. LangChain Agent가 e2e 로그와 RAG 문서를 함께 참조해 AI 분석 리포트 생성

## 1. 자연어 요구사항 확인

```bash
sed -n '1,220p' requirements/trainingjob.txt
```

기대 결과:

- `domain`, `group`, `version`, `kind` 확인
- `specFields`: `image`, `gpuCount`, `pvcName`, `datasetPath`, `outputPath`
- `statusFields`: `phase`, `jobName`, `podName`, `message`
- Controller 책임: TrainingJob을 감지하고 Kubernetes Job 생성

강조 포인트:

- 사용자는 완성된 Go/Kubernetes 코드를 작성하지 않고 자연어 요구사항만 제공합니다.
- Agent는 이 요구사항을 이후 자동화 단계의 기준 스펙으로 변환합니다.

## 2. operator-spec.yaml 생성

```bash
python3 agent/tools/spec_generator.py \
  requirements/trainingjob.txt \
  -o generated/trainingjob-operator-spec.yaml
```

기대 결과:

- `generated/trainingjob-operator-spec.yaml` 생성
- `warnings: []`, `errors: []`
- project/api/spec/status/controller/rbac/validation 구조 확인

강조 포인트:

- `operator-spec.yaml`은 이후 모든 도구가 공유하는 내부 계약입니다.
- LLM을 붙이기 전 MVP에서는 규칙 기반 parser로 동작합니다.

## 3. command plan 생성

```bash
python3 agent/tools/command_planner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --output generated/trainingjob-command-plan.md
```

기대 결과:

- `generated/trainingjob-command-plan.md` 생성
- `kubebuilder init`, `kubebuilder create api`, `make generate`, `make manifests`, `make test` 실행 계획 확인

강조 포인트:

- 실제 명령 실행 전 사람이 검토할 수 있는 계획 문서를 생성합니다.
- 초보자가 어떤 순서로 진행해야 하는지 이해할 수 있습니다.

## 4. scaffold dry-run

```bash
python3 agent/tools/scaffold_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --workspace workspace/generated-operators \
  --dry-run
```

기대 결과:

- 실제 파일을 만들지 않고 실행 예정 명령만 출력
- 대상 프로젝트 경로 확인

강조 포인트:

- 위험한 생성 작업 전에 dry-run으로 명령과 대상 경로를 검토합니다.

## 5. scaffold execute

```bash
python3 agent/tools/scaffold_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --workspace workspace/generated-operators \
  --execute
```

기대 결과:

- `workspace/generated-operators/trainingjob-operator` 생성
- Kubebuilder scaffold 생성
- `make generate`, `make manifests`, `make test` 성공
- `logs/scaffold/<timestamp>/summary.json` 저장

강조 포인트:

- Agent가 명령을 실행하고 stdout/stderr/exit code를 저장합니다.
- 실패 시 어떤 단계에서 실패했는지 추적할 수 있습니다.

## 6. artifact patch

```bash
python3 agent/tools/artifact_patcher.py \
  --input generated/trainingjob-operator-spec.yaml \
  --project workspace/generated-operators/trainingjob-operator \
  --execute
```

기대 결과:

- `api/v1alpha1/trainingjob_types.go`에 spec/status 필드 반영
- `config/samples/ml_v1alpha1_trainingjob.yaml`에 sample spec 반영
- `internal/controller/trainingjob_controller.go`에 RBAC marker 반영
- `logs/patch/<timestamp>/summary.json` 저장

강조 포인트:

- Kubebuilder scaffold만으로 끝나지 않고, 구조화 스펙을 실제 산출물에 반영합니다.
- 현재는 TrainingJob profile 로직이 일부 섞여 있으며 향후 profile/plugin으로 분리할 계획입니다.

## 7. make generate/manifests/test

artifact patch 실행 시 아래 검증 명령이 함께 수행됩니다.

```bash
make generate
make manifests
make test
```

별도로 확인하려면 다음을 실행합니다.

```bash
cd workspace/generated-operators/trainingjob-operator
make generate
make manifests
make test
```

기대 결과:

- deepcopy 코드 생성 성공
- CRD/RBAC manifest 생성 성공
- Go test 성공

강조 포인트:

- 생성 결과가 실제 Kubebuilder 검증 명령을 통과하는지 확인합니다.

## 8. clean e2e 실행

```bash
python3 agent/tools/e2e_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --clean \
  --execute
```

기대 결과:

- kind 클러스터 `trainingjob-e2e` 확인 또는 생성
- CRD 설치 성공
- 기존 TrainingJob/Job/Pod 삭제 및 삭제 확인
- sample PVC 적용
- Controller 실행
- sample TrainingJob CR 적용
- Kubernetes Job 생성 확인
- `logs/e2e/<timestamp>/summary.json` 저장

현재 검증 완료 로그:

```text
logs/e2e/20260607-213346/summary.json
```

강조 포인트:

- 기존 리소스를 정리한 뒤 새로 생성해서 검증합니다.
- 단순 manifest 생성이 아니라 실제 Kubernetes API에서 Controller 동작을 확인합니다.

## 9. Job spec validation 확인

현재 clean e2e 검증 결과:

| 항목 | 기대값 | 실제값 | 결과 |
| --- | --- | --- | --- |
| container image | `busybox:latest` | `busybox:latest` | passed |
| GPU limit | `1` | `1` | passed |
| PVC claimName | `sample-pvc` | `sample-pvc` | passed |
| `/workspace` volumeMount | `workspace` | `workspace` | passed |
| `DATASET_PATH` | `/workspace/dataset` | `/workspace/dataset` | passed |
| `OUTPUT_PATH` | `/workspace/output` | `/workspace/output` | passed |

확인 명령:

```bash
cat logs/e2e/20260607-213346/summary.json
```

강조 포인트:

- Controller가 만든 Job에 요구사항의 spec 값이 실제 반영됐는지 검증합니다.
- Pod 완료 여부만 보는 것이 아니라 Controller 산출물의 정확성을 확인합니다.

## 10. log_analyzer로 성공/경고 분석

```bash
python3 agent/tools/log_analyzer.py \
  --log-dir logs/e2e/20260607-213346
```

기대 결과:

- `logs/e2e/20260607-213346/analysis.md` 생성
- 전체 실행 결과: succeeded
- failedStep: none
- GPU 부족 Pending warning 해석
- Job spec validation passed 반영
- 재실행 권장 명령 포함

강조 포인트:

- 실패 또는 경고가 발생해도 사람이 모든 로그를 직접 읽지 않도록 분석 리포트를 생성합니다.
- kind 클러스터에는 GPU가 없으므로 `Insufficient nvidia.com/gpu`는 실패가 아닌 warning으로 분류합니다.

## 11. LangChain Agent로 e2e 로그 AI 분석

```bash
python3 agent/langchain_agent.py \
  --analyze-log logs/e2e/20260607-213346 \
  --planner llm
```

기대 결과:

- `log_analyzer.py` Tool 호출 성공
- `logs/e2e/20260607-213346/analysis.md` 읽기 성공
- `knowledge-base/troubleshooting/common-errors.md`와 TrainingJob 예시 문서 검색
- Agent report 생성: `logs/agent/<timestamp>/agent-report.md`
- Decision: `succeeded-with-warning`
- Classification: `succeeded-with-gpu-pending-warning`

GPU Pending warning 해석:

- Controller가 Job을 생성하지 못한 오류가 아닙니다.
- Job spec validation은 성공했습니다.
- kind 클러스터에 `nvidia.com/gpu` 리소스가 없어서 Pod가 Pending 상태입니다.
- GPU 노드가 있는 클러스터에서 실행하거나 `gpuCount: 0` e2e sample을 사용하면 Pod 실행 완료까지 검증할 수 있습니다.

강조 포인트:

- Agent가 단순히 로그 분석 도구를 실행하는 데서 끝나지 않고, `summary.json`, `analysis.md`, RAG 검색 문서를 함께 참조해 판단합니다.
- 심사 시연의 planner는 `llm`입니다. API key나 모델 설정이 없으면 다른 planner로 대체하지 않고 명확한 오류를 출력합니다.
- 현재 RAG는 로컬 Markdown `knowledge-base` 검색으로 구현되어 있습니다.
- 안전을 위해 기본 흐름은 dry-run 중심이며, 실제 scaffold/e2e 실행은 별도 `--execute`가 있을 때만 수행합니다.

## 시연 중 강조할 포인트

- 이 시스템은 단순 질의응답 챗봇이 아니라 로컬 파일과 명령을 다루는 실행형 Agent입니다.
- 자연어 요구사항이 `operator-spec.yaml`이라는 내부 스펙으로 변환됩니다.
- 모든 단계는 dry-run, execute, summary log를 통해 추적 가능합니다.
- TrainingJob은 example profile이며 core pipeline은 RedisCache 등 다른 Operator로 확장 가능합니다.
- 검증 실패 시 `log_analyzer.py`가 실패 단계, 원인, 해결 방향을 리포트로 생성할 수 있습니다.
- LangChain Agent는 RAG 검색 결과와 Tool 실행 결과를 결합해 성공/실패/경고를 자연어로 설명합니다.
