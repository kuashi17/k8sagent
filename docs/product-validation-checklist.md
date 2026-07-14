# Product Validation Checklist

이 문서는 Web UI와 CLI로 현재 제품 흐름을 확인하기 위한 점검표입니다.
특정 Operator 예제에 종속되지 않고, 요구사항 입력부터 계획 확인, 코드 생성,
검증, 실패 처리까지의 사용자 여정을 기준으로 작성했습니다.

## 1. 실행 전 환경 확인

### Python 패키지

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 로컬 개발 도구

```bash
./scripts/install-local-tools.sh
export PATH="$PWD/.tools/bin:$PATH"
./scripts/check-env.sh
```

확인 대상:

- Python
- Go
- Docker
- kubectl
- kind
- kubebuilder
- kustomize
- git

### Docker와 kind

kind 검증을 실행하려면 WSL 터미널에서 Docker daemon에 연결되어야 합니다.

```bash
docker info
kind get clusters
```

Docker가 꺼져 있으면 Web 결과 화면은 `DOCKER_DAEMON_UNAVAILABLE`로
빠르게 실패해야 하며, lifecycle 항목은 `not-run`으로 남아야 합니다.

### Local LLM

기본 설정은 Ollama 호환 Local LLM을 사용합니다.

```bash
ollama pull qwen2.5-coder:3b
```

Web/CLI 실행 전 다음 환경변수를 필요에 맞게 설정할 수 있습니다.

```bash
export LOCAL_LLM_BASE_URL=http://localhost:11434/v1
export LOCAL_LLM_MODEL=qwen2.5-coder:3b
```

## 2. Web UI 기본 시나리오

Web 서버를 실행합니다.

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

브라우저에서 접속합니다.

```text
http://localhost:8000
```

확인할 사용자 흐름:

1. 요구사항 입력 화면이 열린다.
2. 예시 버튼을 누르면 textarea에 수정 가능한 요구사항이 채워진다.
3. `안전하게 계획 만들기`를 누르면 실제 파일 생성 전 계획 화면으로 이동한다.
4. 필수 정보가 부족하면 생성하지 않고 보완 질문을 보여준다.
5. 계획 화면에서 관리 리소스, RBAC, 삭제 정책, capability 등급을 확인할 수 있다.
6. 사용자가 승인해야 코드 생성과 검증이 진행된다.
7. 생성 후 결과 화면에서 먼저 볼 파일, 검증 결과, kubectl 확인 명령을 볼 수 있다.
8. kind 검증을 실행하면 create/update/drift/delete/read-only/retain 등 lifecycle evidence가 표시된다.

## 3. 대표 요구사항

### Deployment 관리

```text
CustomerPortal Operator를 만들어 주세요.
API는 apps.sample.io/v1alpha1입니다.

spec:
- image: string
- replicas: int32

status:
- phase: string
- readyReplicas: int32
- message: string

Controller는 Deployment를 생성하고 image와 replicas 변경을 반영해야 합니다.
외부에서 Deployment가 변경되면 spec 기준으로 복구해야 합니다.
CustomerPortal이 삭제되면 Deployment도 함께 삭제해야 합니다.
```

기대 결과:

- 관리 대상은 Deployment만 표시된다.
- 검증된 Deployment lifecycle 패턴이면 stable로 표시된다.
- Service/Pod/Job/PVC가 관리 대상으로 섞이지 않는다.
- kind 검증 성공 시 drift 복구와 삭제 정책 evidence가 기록된다.

### 읽기 전용 Deployment 관찰

```text
ExistingDeploymentWatcher Operator를 만들어 주세요.
API는 monitoring.sample.io/v1alpha1입니다.

spec:
- deploymentName: string
- targetNamespace: string

status:
- phase: string
- observedDeploymentName: string
- desiredReplicas: int32
- readyReplicas: int32
- message: string

Controller는 기존 Deployment를 읽기만 해야 합니다.
Deployment를 새로 생성하거나 수정하거나 삭제하면 안 됩니다.
ExistingDeploymentWatcher가 삭제되어도 기존 Deployment는 유지되어야 합니다.
```

기대 결과:

- 관리 방식은 read-only로 분류된다.
- Deployment RBAC는 get/list/watch 중심이어야 한다.
- create/update/patch/delete 권한은 없어야 한다.
- 삭제 정책은 retain 또는 ownership none으로 표시된다.

### 검증 증거가 부족한 리소스

```text
AppAccessPolicy Operator를 만들어 주세요.
API는 security.sample.io/v1alpha1입니다.

spec:
- appSelector: map[string]string
- allowedFromNamespace: string
- allowedPort: int32
- protocol: string

status:
- phase: string
- networkPolicyName: string
- message: string

Controller는 NetworkPolicy만 생성하고 갱신해야 합니다.
Deployment, Pod, Service, Job, PVC는 생성하지 마세요.
```

기대 결과:

- 관리 대상은 NetworkPolicy만 표시된다.
- 금지한 Deployment/Pod/Service/Job/PVC가 managed/observed resource에 포함되지 않는다.
- NetworkPolicy lifecycle evidence가 부족하면 experimental로 표시된다.
- experimental 확인 체크 전에는 생성 승인이 불가능해야 한다.

## 4. 실패 상태 확인

### Docker 중단

Docker Desktop을 종료한 뒤 kind 검증을 실행합니다.

기대 결과:

- 결과 상태가 infrastructure-failed로 표시된다.
- errorCode는 `DOCKER_DAEMON_UNAVAILABLE`이어야 한다.
- Operator 코드 문제가 아니라 환경 문제로 안내해야 한다.
- lifecycle evidence는 모두 `not-run`이며 capability 승격 근거로 쓰이지 않는다.
- kubectl 명령은 “일부 생성되었을 수 있는 리소스 확인” 용도로만 표시된다.

### 필수 정보 누락

Kind 또는 API group/version이 없는 요구사항을 입력합니다.

기대 결과:

- 임의 값으로 생성하지 않는다.
- clarification-required 상태로 멈춘다.
- 사용자에게 필요한 정보만 질문한다.
- Tool 실행과 workspace 생성은 일어나지 않는다.

### 모순된 삭제 정책

PVC를 유지하라고 하면서 동시에 삭제하라고 요구합니다.

기대 결과:

- 삭제 정책 모순을 감지한다.
- retain/delete 중 하나를 임의 선택하지 않는다.
- 사용자에게 원하는 정책을 확인한다.

## 5. CLI 회귀 확인

빠른 회귀:

```bash
python3 scripts/run-regression-tests.py \
  --suite quick \
  --output-dir evaluation/results/regression/local-quick
```

Local LLM 포함 회귀:

```bash
python3 scripts/run-regression-tests.py \
  --suite standard \
  --output-dir evaluation/results/regression/local-standard
```

Docker/kind 포함 회귀:

```bash
python3 scripts/run-regression-tests.py \
  --suite full \
  --output-dir evaluation/results/regression/local-full
```

회귀 결과는 `evaluation/results/` 아래에 생성되며 git에는 추적하지 않습니다.

## 6. 확인 기준

시연 또는 점검이 성공했다고 판단하는 기준은 다음과 같습니다.

- LLM 계획이 Pydantic 계약 검증을 통과한다.
- 승인되지 않은 Tool은 실행되지 않는다.
- 코드 생성 후 `make generate`, `make manifests`, `make test`가 통과한다.
- kind 검증에서 실제 lifecycle evidence가 기록된다.
- 실패 시 구조화 errorCode와 다음 조치가 표시된다.
- 인프라 실패와 Operator 코드 실패가 분리되어 보인다.
- `not-run` 항목은 성공 evidence로 취급하지 않는다.
