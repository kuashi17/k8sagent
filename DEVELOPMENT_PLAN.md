# Development Plan

## 개발 전략

본 프로젝트는 전체 AI Agent 시스템을 한 번에 구현하지 않고, 로컬 실행형 MVP에서 시작해 RAG, MCP, CI/CD 연계로 확장합니다.

초기 단계에서는 Kubebuilder 개발 흐름을 정확히 정의하고, 실제 검증 명령과 실패 로그 분석이 가능한 구조를 우선 확보합니다.

## Phase 1. 프로젝트 문서 및 구조 정리

목표: 과제 수행을 위한 기본 문서와 디렉터리 구조를 확정합니다.

- 프로젝트 목표 정리
- Pain Point 및 개선 목표 정리
- MVP 범위 확정
- 아키텍처 초안 작성
- 데모 시나리오 작성
- 개발 계획 작성
- Agent 문서, 워크플로우, 정책 디렉터리 구성

## Phase 2. 로컬 환경 점검 흐름 정의

목표: Kubebuilder 개발에 필요한 로컬 도구 설치 여부를 점검하는 절차를 정의합니다.

- `go` 설치 및 버전 확인
- `docker` 설치 및 동작 여부 확인
- `kubectl` 설치 및 버전 확인
- `kind` 설치 및 버전 확인
- `helm` 설치 및 버전 확인
- `kubebuilder` 설치 및 버전 확인
- `kustomize` 설치 및 버전 확인
- `git` 설치 및 버전 확인

## Phase 3. Kubebuilder 개발 흐름 정리

목표: Operator 프로젝트 생성부터 API 생성까지의 표준 흐름을 정리합니다.

- `workspace` 아래 Kubebuilder 프로젝트 생성 위치 정의
- `kubebuilder init` 실행 흐름 정의
- `kubebuilder create api` 실행 흐름 정의
- API group, version, kind 입력 기준 정리
- CRD 타입 정의 기준 정리
- Controller 책임 범위 정리
- RBAC marker 작성 기준 정리

## Phase 4. 검증 명령 실행 흐름 정의

목표: 생성된 Operator 프로젝트가 기본 검증 단계를 통과하는지 확인하는 절차를 정의합니다.

- `make generate` 실행 목적과 성공 기준 정리
- `make manifests` 실행 목적과 성공 기준 정리
- `make test` 실행 목적과 성공 기준 정리
- 검증 로그 저장 위치 정의
- 실패 시 수집해야 할 정보 정의

## Phase 5. 오류 분석 MVP

목표: 검증 실패 시 로그를 해석하고 다음 조치 방향을 제시하는 기준을 마련합니다.

- Go module 오류 유형 정리
- controller-gen 오류 유형 정리
- CRD schema 오류 유형 정리
- RBAC marker 오류 유형 정리
- envtest 오류 유형 정리
- Docker/kind 연계 오류 유형 정리
- 오류별 원인 후보와 권장 조치 문서화

## Phase 6. RAG 기반 지식 검색 확장

목표: Kubebuilder 가이드, 사내 예제 코드, YAML 템플릿, 테스트 샘플을 검색 가능한 지식으로 구성합니다.

- 문서 수집 범위 정의
- 내부 지식베이스 구조 설계
- Vector DB 적용 방식 검토
- 검색 질의 템플릿 정의
- 유사 사례 검색 결과를 생성 컨텍스트로 연결

## Phase 7. Reranker 및 Few-shot 생성 고도화

목표: 검색 결과의 품질을 높이고 산출물 생성 형식의 일관성을 개선합니다.

- Reranker 적용 기준 정의
- 도메인 적합도 높은 문서 선별 기준 수립
- 유사 요구사항과 산출물 예시 정리
- Few-shot 프롬프트 템플릿 구성
- 생성 결과 검증 기준 보강

## Phase 8. MCP 및 CI/CD 연계 확장

목표: 실제 개발·검증·배포 체계와 Agent를 연결합니다.

- MCP 기반 GitHub 연계 구조 설계
- 브랜치, commit, push, PR 초안 생성 흐름 검토
- Jenkins 검증 Job 실행 및 결과 수집 구조 설계
- Harbor 이미지 빌드/푸시 확인 흐름 검토
- Argo CD 배포 상태 확인 흐름 검토

## 1차 MVP 단계별 작업 순서

1. 프로젝트 문서와 디렉터리 구조를 생성합니다.
2. 로컬 환경 점검 항목을 정의합니다.
3. Kubebuilder scaffold 생성 절차를 문서화합니다.
4. 샘플 Operator 요구사항을 작성합니다.
5. API 생성 절차와 구조화 스펙 예시를 작성합니다.
6. `make generate`, `make manifests`, `make test` 검증 흐름을 정리합니다.
7. 실패 로그 분석 기준을 작성합니다.
8. 부분 수정 및 재생성 정책을 정의합니다.
9. 향후 GitHub, Jenkins, Harbor, Argo CD 연계 구조를 정리합니다.

## 현재 MVP 진행 상태

| 단계 | 상태 | 결과 |
| --- | --- | --- |
| 로컬 환경 점검 | 완료 | Go, Docker, kubectl, kind, helm, kubebuilder, kustomize, git 확인 |
| 샘플 요구사항 구조화 | 완료 | `generated/rediscache-operator-spec.yaml` 생성 |
| Kubebuilder scaffold 생성 | 완료 | `workspace/redis-cache-operator` 생성 |
| API 타입 정의 | 완료 | `RedisCache` Spec/Status 필드 반영 |
| CRD manifest 생성 | 완료 | `config/crd/bases/cache.sample.io_rediscaches.yaml` 생성 |
| 기본 컴파일 검증 | 완료 | `go test ./api/... ./cmd/... ./test/utils` 통과 |
| Controller 구현 | 보류 | 1차 MVP에서는 복잡한 Reconcile 로직 제외 |
| Jenkins/Harbor/Argo CD 연계 | 예정 | Phase 8에서 확장 |

## 일반화 진행 상태

| 단계 | 상태 | 결과 |
| --- | --- | --- |
| 요구사항 파일 파싱 | 완료 | TrainingJob 요구사항을 `generated/training-job-operator-spec.yaml`로 변환 |
| 초보자용 interactive CLI | 진행 중 | 공통 질문 흐름과 입력값 검증 추가 |
| 스펙 기반 scaffold | 완료 | `generated/training-job-operator-spec.yaml`에서 `workspace/training-job-operator` 생성 |
| 타입/샘플/CRD 자동 반영 | 완료 | TrainingJob Spec/Status 필드와 샘플 CR 생성 |
| 기본 검증 자동 실행 | 완료 | `make generate`, `make manifests`, `make test` 통과 |
| TrainingJob Controller 실제 로직 | 예정 | Job/PVC/GPU/status reconcile 생성 필요 |

## 다음 진행 순서

1. RedisCache 요구사항을 기준으로 Agent 입력·출력 예시를 정리합니다.
2. `make` 미설치 환경에서도 검증 가능한 대체 명령 흐름을 문서화합니다.
3. controller-tools 버전 호환성 오류를 오류 분석 사례로 등록합니다.
4. RedisCache Controller 구현 범위를 2차 MVP 후보로 분리합니다.
5. GitHub/Jenkins 연계 전, 로컬 로그 수집과 오류 분류 포맷을 먼저 확정합니다.
6. TrainingJob 스펙을 기준으로 Job 생성 Controller 템플릿을 구현합니다.
