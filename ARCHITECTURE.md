# Architecture

## 개요

본 시스템은 Kubebuilder 기반 Kubernetes Operator 개발을 지원하는 로컬 실행형 AI Agent 구조를 지향합니다.

사용자는 자연어로 Operator 요구사항을 입력하고, Agent는 이를 구조화된 개발 스펙으로 변환한 뒤 Kubebuilder 개발 절차에 맞춰 산출물 생성, 검증 명령 실행, 실패 로그 분석, 수정 방향 제시를 수행합니다.

## 전체 흐름

```text
User Requirement
      |
      v
Requirement Analyzer
      |
      v
Structured Operator Spec
      |
      v
RAG Retriever + Reranker
      |
      v
Agent Workflow Planner
      |
      v
Artifact Generator
      |
      v
Command Executor
      |
      v
Validation Analyzer
      |
      v
Error Diagnosis / Partial Regeneration
      |
      v
GitHub / Jenkins / Harbor / Argo CD Extension
```

## 주요 컴포넌트

| 컴포넌트 | 역할 |
| --- | --- |
| Requirement Analyzer | 자연어 요구사항을 리소스 구조, Spec/Status 필드, Reconcile 책임, 권한 범위로 구조화 |
| RAG Retriever | Kubebuilder 가이드, 사내 예제 코드, YAML 템플릿, 테스트 샘플 검색 |
| Reranker | 검색 결과 중 도메인 적합도가 높은 참조 문서를 우선 선별 |
| Agent Workflow Planner | 요구사항 분석, 생성, 검증, 오류 분석 단계를 실행 순서로 구성 |
| Artifact Generator | CRD, Controller, RBAC, Manifest, 테스트 초안 생성 지원 |
| Command Executor | `make generate`, `make manifests`, `make test` 등 검증 명령 실행 담당 |
| Validation Analyzer | 명령 실행 결과와 로그를 분석하여 성공/실패 여부 판단 |
| Error Diagnosis Agent | 오류 원인 후보, 수정 포인트, 다음 조치 방향 제시 |
| Extension Adapter | GitHub, Jenkins, Harbor, Argo CD 연계를 위한 확장 계층 |

## 로컬 작업 공간 구조

Agent 프로젝트 루트와 실제 Kubebuilder 프로젝트는 분리합니다.

```text
C:\k8sagent
├── agent
├── docs
├── generated
├── logs
└── workspace
    └── sample-operator
```

`workspace` 아래에 실제 Kubebuilder 프로젝트를 생성하면 Agent 문서, 실행 로그, 생성 산출물, 대상 Operator 프로젝트가 섞이지 않습니다.

## 1차 MVP 아키텍처

1차 MVP에서는 다음 범위에 집중합니다.

- 로컬 환경 점검
- Kubebuilder scaffold 생성 절차 정의
- 예시 API 생성 절차 정의
- `make generate`, `make manifests`, `make test` 실행 흐름 정의
- 실패 로그 분석 기준 정리

다음 항목은 1차 MVP에서 직접 구현하지 않고, 확장 가능한 구조로만 문서화합니다.

- Vector DB 기반 RAG 인덱스
- Reranker 기반 검색 결과 재정렬
- MCP 기반 GitHub/Jenkins 연계
- Harbor 이미지 저장소 연계
- Argo CD 배포 상태 확인
- 자동 PR 생성 및 배포 파이프라인 연계

## 확장 방향

### GitHub 연계

- 기존 유사 구현 검색
- 템플릿 프로젝트 참조
- 생성 결과 브랜치 반영
- commit, push, PR 초안 생성

### Jenkins 연계

- 검증 Job 실행
- 빌드 및 테스트 결과 수집
- 실패 로그 요약
- 후속 조치 추천

### Harbor 연계

- Operator 이미지 빌드 결과 확인
- 이미지 태그 관리
- 이미지 푸시 성공 여부 확인

### Argo CD 연계

- 배포 반영 상태 확인
- Sync/Health 상태 수집
- 배포 실패 원인 분석

