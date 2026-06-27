# Architecture

## 개요

본 시스템은 Kubebuilder 기반 Kubernetes Operator 개발을 지원하는 로컬 실행형 AI Agent 구조를 지향합니다.

사용자는 자연어로 Operator 요구사항을 입력하고, Agent는 이를 구조화된 개발 스펙으로 변환한 뒤 Kubebuilder 개발 절차에 맞춰 산출물 생성, 검증 명령 실행, 실패 로그 분석, 수정 방향 제시를 수행합니다.

## 전체 흐름

```text
User Requirement
      |
      v
operator-spec.yaml
      |
      v
Command Plan
      |
      v
Kubebuilder Scaffold
      |
      v
Artifact Patch
      |
      v
Validation
      |
      v
kind E2E
      |
      v
Log Analysis
```

현재 로컬 MVP 파이프라인은 다음 산출물 흐름을 기준으로 동작합니다.

```text
requirement
  -> generated/<kind>-operator-spec.yaml
  -> generated/<kind>-command-plan.md
  -> workspace/generated-operators/<kind>-operator
  -> logs/scaffold/<timestamp>/summary.json
  -> logs/patch/<timestamp>/summary.json
  -> logs/e2e/<timestamp>/summary.json
  -> logs/e2e/<timestamp>/analysis.md
```

향후 RAG Retriever, Reranker, GitHub/Jenkins/Harbor/Argo CD 연계는 이 파이프라인의 앞뒤에 붙는 확장 계층으로 둡니다.

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

## Core Agent와 Profile/Plugin 구분

이 프로젝트는 특정 Operator를 생성하는 단일 목적 도구가 아니라 Kubebuilder 기반 Operator 개발 절차를 자동화하는 범용 Agent 시스템입니다.

따라서 구현은 다음 두 계층으로 나눕니다.

| 계층 | 역할 | 예 |
| --- | --- | --- |
| Core Agent | Operator 종류와 무관하게 공통으로 필요한 절차를 수행 | 요구사항 구조화, Kubebuilder 실행 계획, scaffold 실행, 로그 저장 |
| Profile/Plugin | 특정 Operator 패턴의 보정, 검증, e2e 규칙을 제공 | TrainingJob Job/GPU/PVC 검증, RedisCache StatefulSet/Service 검증 |

TrainingJob은 GPU 학습 도메인을 대상으로 한 MVP 검증용 profile/example입니다. RedisCache, BackupJob, QueueWorker, BatchProcessor 같은 다른 Operator는 별도 profile로 확장할 수 있습니다.

## 현재 도구의 계층 구분

| 도구 | 현재 역할 | 계층 판단 |
| --- | --- | --- |
| `agent/tools/spec_generator.py` | 자연어 요구사항을 `operator-spec.yaml`로 변환 | 범용 core |
| `agent/tools/command_planner.py` | 스펙 기반 Kubebuilder 실행 계획 생성 | 범용 core |
| `agent/tools/scaffold_runner.py` | Kubebuilder scaffold, preflight, generate/manifests/test 실행 | 범용 core |
| `agent/tools/artifact_patcher.py` | API 타입, sample, RBAC marker 보정 | core와 TrainingJob profile 로직이 일부 섞임 |
| `agent/tools/e2e_runner.py` | `job-workload-v1` profile용 legacy 호환 adapter | 명시적 Pydantic profile 계약, 특정 CR 기본값 없음 |
| `agent/tools/log_analyzer.py` | summary/log 분석과 오류 유형 분류 | core와 TrainingJob 재실행/검증 단계명이 일부 섞임 |

범용 lifecycle은 `kind_deployment_runner.py`와 validator 계약이 담당합니다.
legacy `e2e_runner.py`는 Job/Pod/PVC 검증이 필요한 profile만
`e2e.validator: job-workload-v1`로 명시해 사용할 수 있으며, profile이 없거나
계약이 불완전하면 Tool 실행 전에 거부합니다.

## Profile 예시

`profiles/` 디렉터리는 특정 Operator 패턴의 검증 규칙과 기본값을 정의합니다.

```text
profiles
├── trainingjob.yaml
└── rediscache.yaml
```

- `trainingjob.yaml`: Kubernetes Job 생성, Pod/PVC 참조, GPU limit, `/workspace` mount, `DATASET_PATH`/`OUTPUT_PATH` env 검증 규칙
- `rediscache.yaml`: StatefulSet, Service, PVC 기반 RedisCache Operator 검증 규칙 placeholder

## 로컬 작업 공간 구조

Agent 프로젝트 루트와 실제 Kubebuilder 프로젝트는 분리합니다.

```text
C:\k8sagent
├── agent
├── docs
├── profiles
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
- TrainingJob profile을 이용한 kind 기반 e2e 검증

다음 항목은 1차 MVP에서 직접 구현하지 않고, 확장 가능한 구조로만 문서화합니다.

- Vector DB 기반 RAG 인덱스
- Reranker 기반 검색 결과 재정렬
- MCP 기반 GitHub/Jenkins 연계
- Harbor 이미지 저장소 연계
- Argo CD 배포 상태 확인
- 자동 PR 생성 및 배포 파이프라인 연계
- profile/plugin 동적 로딩 구조

## 확장 방향

### Profile/Plugin 확장

- profile별 sample 기본값 정의
- profile별 하위 리소스 검증 규칙 정의
- profile별 warning 처리 규칙 정의
- profile별 patch 규칙과 e2e 검증 규칙 분리
- core 도구는 `operator-spec.yaml`과 profile 설정을 읽어 공통 실행 흐름만 담당

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
