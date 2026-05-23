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
| `generated` | Agent가 생성하는 중간 산출물 또는 스펙 저장 위치 |
| `logs` | 명령 실행 결과와 실패 로그 저장 위치 |
| `workspace` | 실제 Kubebuilder 프로젝트가 생성될 작업 공간 |

## 현재 상태

현재 단계에서는 구현 코드를 작성하지 않고, 과제 수행을 위한 문서와 디렉터리 구조를 먼저 구성합니다.

