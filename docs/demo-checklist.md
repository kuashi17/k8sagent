# Demo Checklist

## 1. 시연 전 준비사항

### Docker 실행 여부

```bash
docker ps
```

성공 기준:

- Docker daemon에 연결된다.
- permission denied가 발생하지 않는다.

실패 시:

- Docker Desktop 또는 Docker daemon을 실행한다.
- WSL 환경이면 Docker Desktop WSL integration을 확인한다.
- 사용자 권한 문제면 현재 셸에서 `docker ps`가 되는지 먼저 확인한다.

### kind 클러스터 상태

```bash
kind get clusters
```

성공 기준:

- `trainingjob-e2e` 클러스터가 보이거나, e2e 실행 시 새로 생성할 수 있는 상태다.

실패 시:

- kind 설치 여부를 확인한다.
- Docker 연결 상태를 먼저 확인한다.

### kubectl context 확인

```bash
kubectl config current-context
kubectl cluster-info --context kind-trainingjob-e2e
```

성공 기준:

- `kind-trainingjob-e2e` context가 존재한다.
- Kubernetes API server에 연결된다.

실패 시:

- `kind create cluster --name trainingjob-e2e`로 클러스터를 생성한다.
- `kubectl config use-context kind-trainingjob-e2e`를 실행한다.

### go/kubebuilder/make 확인

```bash
go version
kubebuilder version
make --version
```

성공 기준:

- 세 명령 모두 정상 출력된다.

실패 시:

- 로컬 도구 설치 스크립트 또는 시스템 패키지 설치를 확인한다.
- 프로젝트 로컬 도구 경로가 필요하면 다음을 적용한다.

```bash
export PATH="/home/ch0618/k8sagent/.tools/bin:$PATH"
```

### 기존 리소스 정리 필요 여부

clean e2e는 기존 리소스를 자동 정리한다.

```bash
python3 agent/tools/e2e_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --profile profiles/trainingjob.yaml \
  --clean \
  --dry-run
```

성공 기준:

- 삭제 예정 리소스와 재생성 계획을 확인할 수 있다.
- PVC는 기본적으로 유지되며, PVC까지 지우려면 `--delete-pvc`를 사용한다.

## 2. 시연 순서 체크리스트

### 1. requirement 확인

```bash
sed -n '1,220p' requirements/trainingjob.txt
```

체크:

- TrainingJob 요구사항이 보인다.
- domain/group/version/kind, spec/status, Controller 책임을 설명할 수 있다.

### 2. spec_generator 실행

```bash
python3 agent/tools/spec_generator.py \
  requirements/trainingjob.txt \
  -o generated/trainingjob-operator-spec.yaml
```

체크:

- `generated/trainingjob-operator-spec.yaml` 생성
- `warnings: []`
- `errors: []`

### 3. command_planner 실행

```bash
python3 agent/tools/command_planner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --output generated/trainingjob-command-plan.md
```

체크:

- `generated/trainingjob-command-plan.md` 생성
- Kubebuilder 명령 순서와 목적이 문서화됨

### 4. scaffold_runner dry-run

```bash
python3 agent/tools/scaffold_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --workspace workspace/generated-operators \
  --dry-run
```

체크:

- 실제 실행 없이 예정 명령만 출력
- 대상 프로젝트 경로 확인

### 5. scaffold_runner execute

```bash
python3 agent/tools/scaffold_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --workspace workspace/generated-operators \
  --execute
```

체크:

- `workspace/generated-operators/trainingjob-operator` 생성
- scaffold summary가 `logs/scaffold/<timestamp>/summary.json`에 저장
- `make generate`, `make manifests`, `make test` 성공

주의:

- 대상 디렉터리가 이미 있으면 기본적으로 중단될 수 있다.
- 재생성이 필요할 때만 `--force`를 사용한다.

### 6. artifact_patcher dry-run

```bash
python3 agent/tools/artifact_patcher.py \
  --input generated/trainingjob-operator-spec.yaml \
  --project workspace/generated-operators/trainingjob-operator \
  --dry-run
```

체크:

- 수정 전후 diff 출력
- 실제 파일은 수정되지 않음

### 7. artifact_patcher execute

```bash
python3 agent/tools/artifact_patcher.py \
  --input generated/trainingjob-operator-spec.yaml \
  --project workspace/generated-operators/trainingjob-operator \
  --execute
```

체크:

- API 타입에 spec/status 필드 반영
- sample YAML 반영
- RBAC marker 반영
- patch summary가 `logs/patch/<timestamp>/summary.json`에 저장

### 8. make generate/manifests/test

```bash
cd workspace/generated-operators/trainingjob-operator
make generate
make manifests
make test
cd /home/ch0618/k8sagent
```

체크:

- 세 명령 모두 성공
- CRD/RBAC manifest와 Go test 통과 확인

### 9. e2e_runner clean execute

```bash
python3 agent/tools/e2e_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --profile profiles/trainingjob.yaml \
  --clean \
  --execute
```

체크:

- kind 클러스터 확인 또는 생성
- CRD 설치 성공
- 기존 TrainingJob/Job/Pod 정리
- sample PVC 적용
- Controller 실행
- TrainingJob CR 적용
- Kubernetes Job 생성 확인
- Job spec validation 통과
- summary가 `logs/e2e/<timestamp>/summary.json`에 저장

### 10. log_analyzer 실행

```bash
python3 agent/tools/log_analyzer.py \
  --log-dir logs/e2e/20260531-130345
```

체크:

- `analysis.md` 생성
- 전체 결과, warning, Job spec validation, 재실행 명령 확인

참고:

- 실제 시연에서 새 e2e 로그가 생성되면 `<timestamp>`를 최신 경로로 바꾼다.

## 3. 각 단계별 성공 기준

| 단계 | 성공 기준 |
| --- | --- |
| requirement 확인 | 요구사항 파일에서 Operator 목적과 필드가 확인됨 |
| spec 생성 | `operator-spec.yaml` 생성, `errors` 비어 있음 |
| command plan | Kubebuilder 실행 순서가 Markdown으로 생성됨 |
| scaffold dry-run | 실행 예정 명령과 대상 경로 확인 |
| scaffold execute | Kubebuilder 프로젝트 생성 및 기본 검증 성공 |
| artifact patch dry-run | 수정 diff 확인 |
| artifact patch execute | 타입, sample, RBAC 반영 및 검증 성공 |
| make 검증 | `make generate`, `make manifests`, `make test` 모두 성공 |
| clean e2e | CRD 설치, CR 생성, Job 생성, status 갱신 확인 |
| log analysis | `analysis.md` 생성, 실패/경고/재실행 명령 요약 |

## 4. 실패 시 대처 방법

| 증상 | 원인 후보 | 대처 |
| --- | --- | --- |
| `docker ps` permission denied | Docker 권한 또는 daemon 문제 | Docker Desktop/daemon 실행, WSL integration 확인 |
| `kind` 명령 실패 | kind 미설치 또는 Docker 연결 실패 | kind 설치 확인, Docker 상태 확인 |
| `kubectl cluster-info` 실패 | context 없음 또는 cluster 미실행 | `kind get clusters`, `kubectl config use-context` 확인 |
| `make` 없음 | make 미설치 | `sudo apt install make` 또는 환경 설치 확인 |
| `make generate` 실패 | controller-gen 버전/설치 문제 | Makefile controller-gen 버전과 PATH 확인 |
| `make test` 실패 | Go/envtest/컴파일 문제 | stderr 로그와 `logs/*/summary.json` 확인 |
| CRD 조회 실패 | `make install` 실패 또는 API 등록 지연 | `make install` 재실행, `kubectl get crd` 확인 |
| e2e에서 Pod Pending | GPU 부족 또는 PVC/Image 문제 | Pod events 확인. GPU 부족이면 warning 처리 가능 |
| ImagePullBackOff | 이미지 이름 또는 registry 접근 문제 | sample image와 pull 권한 확인 |
| PVC not found | sample이 없는 PVC를 참조 | PVC 생성 또는 `spec.pvcName` 수정 |

실패 로그 분석:

```bash
python3 agent/tools/log_analyzer.py \
  --log-dir logs/e2e/<timestamp>
```

## 5. 시연 중 강조할 포인트

- 이 시스템은 단순 답변 생성이 아니라 로컬 실행형 Agent 흐름이다.
- 자연어 요구사항이 `operator-spec.yaml`로 구조화된다.
- Kubebuilder 명령 실행 전 command plan과 dry-run으로 안전하게 검토한다.
- 생성된 산출물은 `make generate`, `make manifests`, `make test`로 검증한다.
- kind e2e로 실제 Kubernetes 클러스터에서 Controller 동작을 확인한다.
- TrainingJob은 example profile이고 core Agent는 RedisCache 등 다른 Operator로 확장 가능하다.
- 실패와 warning은 summary와 analysis 리포트로 추적한다.

## 6. 시연 후 보여줄 로그 파일 경로

현재 검증 완료 로그:

```text
logs/e2e/20260531-130345/summary.json
logs/e2e/20260531-130345/analysis.md
logs/e2e/20260531-130345/18-kubectl-get-job.stdout.log
logs/e2e/20260531-130345/19-kubectl-get-pods.stdout.log
logs/e2e/20260531-130345/20-kubectl-get-trainingjob-status.stdout.log
```

새로 실행한 경우:

```bash
find logs/e2e -maxdepth 2 -name summary.json | sort | tail
```

## 7. 발표자가 말할 핵심 문장 5개

1. "이 시스템은 Operator 코드를 단순 생성하는 챗봇이 아니라, 요구사항 해석부터 검증과 로그 분석까지 연결하는 로컬 실행형 Agent입니다."
2. "자연어 요구사항은 `operator-spec.yaml`이라는 내부 계약으로 변환되고, 이후 모든 단계는 이 스펙을 기준으로 실행됩니다."
3. "TrainingJob은 GPU 학습 도메인을 대상으로 한 MVP profile이며, Agent core는 RedisCache 같은 다른 Operator로 확장할 수 있습니다."
4. "clean e2e는 기존 리소스를 지우고 새로 Custom Resource를 생성해 Controller가 실제 Kubernetes Job을 만드는지 검증합니다."
5. "kind 환경의 GPU 부족 Pending은 Job spec 검증이 성공했기 때문에 실패가 아니라 분석 가능한 warning으로 기록합니다."
