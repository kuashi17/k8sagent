# Refactoring Plan

## 목적

현재 MVP는 TrainingJob 예제를 통해 자연어 요구사항부터 kind e2e 검증과 로그 분석까지 end-to-end 흐름을 검증했습니다.

다음 단계의 목표는 TrainingJob 전용 도구로 굳어지지 않도록 구현을 `범용 Agent core`와 `example profile/plugin`으로 분리하는 것입니다.

## 현재 파일별 범용성 점검

| 파일 | 현재 역할 | 범용성 판단 | TrainingJob/Profile 지식 |
| --- | --- | --- | --- |
| `agent/tools/spec_generator.py` | 요구사항 파일을 `operator-spec.yaml`로 변환 | 대체로 범용 core | Kubernetes 기본 리소스 alias 정도만 포함 |
| `agent/tools/command_planner.py` | Kubebuilder 명령 계획 생성 | 범용 core | 없음 |
| `agent/tools/scaffold_runner.py` | scaffold, preflight, generate/manifests/test 실행 | 범용 core | 환경 호환용 Makefile/test patch가 정책으로 섞임 |
| `agent/tools/artifact_patcher.py` | API 타입, sample, RBAC marker 보정 | 부분 범용 | sample 기본값, Job/Pod/PVC RBAC 보강, PVC/path/image 추론 |
| `agent/tools/e2e_runner.py` | legacy Job workload e2e | profile 계약 adapter | `job-workload-v1`이 선언한 CRD, Job 이름, Pod label, GPU/PVC/env 검증 |
| `agent/tools/log_analyzer.py` | summary/log 분석 리포트 생성 | 부분 범용 | TrainingJob 재실행 명령과 e2e 단계명 일부 하드코딩 |

## Core로 유지할 부분

- `operator-spec.yaml` 스키마 읽기와 필수값 검증
- Kubebuilder `init`, `create api`, `make generate`, `make manifests`, `make test` 실행 계획
- dry-run, execute, preflight 실행 모드
- stdout/stderr/exit code/summary.json 로그 저장
- `summary.json` 기반 성공/실패 판정
- failed step 기준 stdout/stderr 추적
- 일반 오류 유형 분류

## Profile/Plugin으로 분리할 부분

- profile별 관리 리소스와 참조 리소스
- sample Custom Resource 기본값
- sample 보조 리소스 생성 규칙
- 하위 리소스 이름 규칙
- 하위 리소스 조회 label selector
- 하위 리소스 spec validation
- domain-specific warning 처리
- profile별 재실행 명령 템플릿
- profile별 artifact patch 규칙

## 리팩터링 우선순위

### 1. `e2e_runner.py` — 1차 완료

가장 TrainingJob 특화가 강한 파일입니다.

현재는 특정 CR/CRD fallback을 제거했습니다. Pydantic으로 검증된
`job-workload-v1` profile이 있을 때만 Agent Tool capability에 노출되며,
그 밖의 리소스는 공통 `kind_deployment_runner.py`로 검증합니다.

분리 목표:

- core: kind cluster 준비, CRD 설치, controller 실행, sample apply, 로그 저장
- profile: CRD 이름, CR kind/resource 이름, 하위 리소스 조회, Job spec validation, GPU Pending warning 규칙

### 2. `artifact_patcher.py`

API 타입과 RBAC marker 반영은 core로 유지하되, sample 값과 profile별 RBAC 보강은 분리합니다.

분리 목표:

- core: spec/status 필드 반영, json tag, validation marker, RBAC marker 렌더링
- profile: TrainingJob sample 값, Job/Pod/PVC 권한 보강, RedisCache StatefulSet/Service sample 값

### 3. `log_analyzer.py`

summary/log 분석은 core로 유지하되, TrainingJob 단계명과 재실행 명령 하드코딩을 제거합니다.

분리 목표:

- core: summary 읽기, failedStep 추적, 로그 evidence 추출, Markdown 생성
- profile: warning 해석, domain-specific evidence 수집, profile별 재실행 명령

## 1차 리팩터링 목표

- `profiles/trainingjob.yaml`과 `profiles/rediscache.yaml`을 profile 정의의 출발점으로 사용
- `e2e_runner.py`가 검증된 profile 계약만 읽도록 강제 (완료)
- TrainingJob Job spec validation 규칙을 profile 파일로 이전 (완료)
- README와 ARCHITECTURE에 core/profile 구분 명확화

## 2차 확장 목표

- `artifact_patcher.py`에 profile 기반 sample generation hook 추가
- `log_analyzer.py`에 profile 기반 warning/evidence rule 추가
- RedisCache profile 기반 e2e 검증 추가
- 사내 Operator 예제 profile 추가
- 이후 LLM/RAG parser가 profile 후보를 추천하도록 확장
