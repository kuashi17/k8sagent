# Demo Video Scenario

이 문서는 제품 흐름을 짧은 동영상으로 보여주기 위한 권장 시나리오입니다.
목표는 기능을 모두 나열하는 것이 아니라, 사용자가 자연어 요구사항을 입력했을 때
Agent가 안전하게 계획하고, 승인 후 코드를 만들고, 검증 근거를 남기는 과정을
선명하게 보여주는 것입니다.

## 권장 영상 길이

- 짧은 버전: 5~7분
- 자세한 버전: 8~12분

권장 구성은 다음 세 장면입니다.

1. 정상 생성: Deployment를 관리하는 Operator 생성
2. 안전장치: 누락/모순 요구사항은 실행 전 중단
3. 증거 확인: make/kind 검증 결과와 kubectl 확인 명령

## 촬영 전 준비

터미널에서 환경을 확인합니다.

```bash
git status --short
./scripts/check-env.sh
docker info
curl -fsS http://localhost:11434/api/tags | python3 -m json.tool | sed -n '1,80p'
```

Web UI를 실행합니다.

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

브라우저에서 접속합니다.

```text
http://localhost:8000
```

촬영 전 불필요한 화면은 닫고, Docker Desktop과 Ollama가 실행 중인지 확인합니다.

Local LLM은 첫 요청이 느릴 수 있으므로 촬영 전에 한 번 짧게 예열합니다.
아래 요청이 1분 이상 걸리면 영상 촬영 중 계획 생성이 멈춘 것처럼 보일 수 있으므로,
Ollama를 재시작하거나 모델 실행 상태를 먼저 정리합니다.

```bash
python3 - <<'PY'
import json
import time
import urllib.request

payload = json.dumps({
    "model": "qwen2.5-coder:3b",
    "prompt": "Return OK.",
    "stream": False,
    "options": {"num_predict": 4, "num_ctx": 512},
}).encode()
request = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=payload,
    headers={"Content-Type": "application/json"},
)
start = time.time()
with urllib.request.urlopen(request, timeout=60) as response:
    result = json.loads(response.read().decode())
print(f"elapsed={time.time() - start:.1f}s response={result.get('response', '').strip()}")
PY
```

이 확인은 제품 기능 검증이 아니라 시연 안정성을 위한 준비입니다. Local LLM이 느린
상태라면 화면의 경과 시간 표시와 로그 영역을 함께 보여주거나, 이미 완료된 최근
작업을 열어 결과 확인 장면부터 촬영합니다.

## 장면 1. 문제와 제품 소개

### 화면

- README 상단 또는 Web UI 첫 화면

### 말할 내용

```text
이 시스템은 Kubernetes Operator를 처음 만드는 개발자가 자연어 요구사항을 입력하면,
AI Agent가 먼저 안전한 계획을 만들고, 사용자가 승인한 뒤 Kubebuilder 프로젝트와
Controller 코드를 생성·검증하는 로컬 실행형 개발지원 도구입니다.

핵심은 LLM 답변을 그대로 복사하는 것이 아니라, Pydantic 계약과 Tool allowlist로
검증한 계획만 실행한다는 점입니다.
```

### 보여줄 포인트

- “먼저 계획하고, 승인 후 실행합니다” 문구
- 요구사항 입력 도움말
- 예시 버튼
- 최근 작업/실패 로그 분석 영역은 짧게만 보여줍니다.

## 장면 2. 정상 생성 시나리오

### 입력 요구사항

Web UI textarea에 아래 요구사항을 입력합니다.

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

### 화면 조작

1. `안전하게 계획 만들기` 클릭
2. 계획 화면에서 관리 대상이 `Deployment`인지 확인
3. Capability가 stable 또는 검증 근거가 있는 패턴으로 표시되는지 확인
4. RBAC, 삭제 정책, 먼저 볼 파일을 짧게 설명
5. 생성 승인 버튼 클릭

### 말할 내용

```text
Agent는 Custom Resource 이름과 API, spec/status 필드, 관리 대상 Deployment를
구조화합니다. 여기서 바로 파일을 만들지 않고 먼저 계획을 보여줍니다.

사용자가 이 계획을 확인하고 승인해야 실제 Kubebuilder scaffold와 코드 생성이
진행됩니다.
```

### 성공 화면에서 보여줄 포인트

- 완료한 단계
  - spec_generator
  - command_planner
  - scaffold_runner
  - artifact_patcher
  - validation
- `make generate`, `make manifests`, `make test` 검증 완료
- 생성된 파일 경로
- “이 Controller가 무엇을 감시하는지”
- “왜 이 RBAC이 필요한지”
- “삭제하면 어떻게 되는지”

## 장면 3. Kubernetes kind 검증

### 화면 조작

1. 결과 화면에서 Kubernetes 검증 실행
2. 진행 화면의 현재 단계와 경과 시간 표시 확인
3. 검증 완료 후 lifecycle evidence 확인
4. kubectl 복사 버튼 또는 명령 영역 확인

### 말할 내용

```text
코드 생성이 끝난 뒤에는 kind 클러스터에서 실제 lifecycle을 검증할 수 있습니다.
단순히 파일이 생성됐다는 것에서 끝나지 않고, 생성, 수정, 외부 drift 복구,
삭제 정책까지 확인합니다.
```

### 보여줄 evidence

- idempotency
- driftRecovery
- rbacLeastPrivilege
- deletionPolicy
- stateMachine 또는 status 관련 항목

가능하면 터미널에서 한 번만 확인합니다.

```bash
kubectl --context <화면에 표시된 context> -n <화면에 표시된 namespace> get all
```

영상에서는 전체 YAML을 길게 보여주기보다, UI가 제공하는 kubectl 명령과 evidence를
중심으로 보여주는 편이 좋습니다.

## 장면 4. 안전장치 시나리오

정상 생성만 보여주면 “그냥 생성기”처럼 보일 수 있습니다. 짧게 하나의 실패/중단
케이스를 보여주면 Agent의 가치가 더 잘 드러납니다.

### 입력 요구사항

```text
이미지와 replicas 값을 받아서 Deployment를 생성하는 Operator를 만들고 싶습니다.
API는 apps.sample.io/v1alpha1을 사용하고 싶습니다.
status에서는 준비된 replicas 수와 처리 결과를 보고 싶습니다.
```

### 기대 결과

- Custom Resource 이름(kind)이 없다고 안내
- 임의 kind를 만들지 않음
- Tool 실행 없음
- workspace와 generated 산출물 없음
- 다음 질문이 명확함

### 말할 내용

```text
필수 정보가 부족하면 Agent는 임의로 값을 만들어 실행하지 않습니다.
이 경우 Custom Resource 이름이 없기 때문에 clarification-required 상태로 멈추고,
사용자에게 필요한 정보만 질문합니다.
```

## 장면 5. 검증 부족 capability 표시

시간이 있으면 experimental capability를 짧게 보여줍니다.

### 입력 요구사항

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

### 보여줄 포인트

- NetworkPolicy만 관리 대상으로 잡히는지
- Service/Deployment/Pod/Job/PVC가 섞이지 않는지
- NetworkPolicy lifecycle evidence가 부족하면 experimental로 표시되는지
- experimental 확인 체크가 필요한지

### 말할 내용

```text
experimental은 새 Operator라서 붙는 등급이 아니라, 관리하려는 Kubernetes 리소스
패턴의 kind lifecycle 증거가 아직 부족하다는 뜻입니다.
검증 증거가 부족한 기능은 사용자가 확인해야 실행할 수 있습니다.
```

## 장면 6. 마무리

### 화면

- README의 시스템 구조 또는 결과 화면
- 가능하면 `docs/current-system-status.md`

### 말할 내용

```text
정리하면 이 시스템은 Local LLM, RAG, 구조화 계약, 안전한 Tool 실행,
Kubebuilder 검증, kind runtime evidence를 하나의 흐름으로 연결합니다.

LLM은 판단과 설명을 담당하고, 실제 파일 생성과 클러스터 변경은 검증된 Tool만
수행합니다. 그래서 초보자도 계획을 먼저 확인하고, 결과와 실패 원인을 이해하면서
Operator 개발을 진행할 수 있습니다.
```

## 촬영 중 피해야 할 것

- 긴 YAML 전체를 오래 보여주지 않습니다.
- 테스트 로그 전체를 스크롤하지 않습니다.
- 내부 파일명을 하나하나 설명하지 않습니다.
- experimental 기능을 stable처럼 말하지 않습니다.
- Docker/kind 실패를 Operator 코드 실패처럼 말하지 않습니다.

## 영상 후 확인하면 좋은 명령

영상 촬영 후 저장소와 검증 상태를 확인합니다.

```bash
git status --short
python3 scripts/run-regression-tests.py --suite quick --output-dir /tmp/k8sagent-demo-video-quick
```

full 검증은 시간이 오래 걸리므로 촬영 직전 또는 릴리스 전 확인용으로 사용합니다.

```bash
python3 scripts/run-regression-tests.py --suite full --output-dir /tmp/k8sagent-demo-video-full
```
