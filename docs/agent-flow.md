# Agent Flow

## 목적

이 문서는 AI Agent가 Kubebuilder 기반 Operator 개발을 지원할 때 따라야 할 전체 흐름을 정의합니다.

## 기본 흐름

1. 사용자 요구사항을 입력받습니다.
2. 요구사항을 구조화된 Operator 스펙으로 변환합니다.
3. 필요한 참조 문서와 유사 사례를 검색합니다.
4. 개발 단계별 작업 계획을 생성합니다.
5. Kubebuilder scaffold 생성 절차를 안내합니다.
6. API 생성 및 산출물 작성 흐름을 안내합니다.
7. 검증 명령을 실행하거나 실행 방법을 제시합니다.
8. 명령 결과와 로그를 분석합니다.
9. 실패 시 원인 후보와 해결 방향을 제시합니다.
10. 필요 시 특정 산출물만 부분 수정 또는 재생성합니다.

## Agent 판단 기준

- 사용자의 요구사항이 충분히 구체적인지 확인합니다.
- API group, version, kind가 명확한지 확인합니다.
- Spec/Status 필드가 Kubernetes CRD schema로 표현 가능한지 확인합니다.
- Controller 책임이 Reconcile 로직으로 구현 가능한 단위인지 확인합니다.
- RBAC 권한 범위가 과도하거나 부족하지 않은지 확인합니다.
- 검증 실패 시 전체 재생성보다 부분 수정이 가능한지 우선 판단합니다.

## 실행 단계

현재 Agent는 계획 단계와 실행 단계를 분리한다.

1. `dry-run` 단계에서는 요구사항을 구조화하고 Tool 계획, 위험, 누락 정보를 보여준다.
2. 사용자가 승인하면 `execute` 단계에서 허용된 Tool만 실제 파일을 생성한다.
3. 코드 생성 후 `make generate`, `make manifests`, `make test`를 실행한다.
4. Docker/kind가 준비된 경우 별도 승인으로 runtime lifecycle을 검증한다.
5. 실패 시 구조화 errorCode와 실제 stdout/stderr 근거를 기록하고, 복구 계획은 자동 실행하지 않는다.

이 구조 덕분에 LLM은 계획과 설명을 담당하고, 실제 변경은 검증된 Tool wrapper만 수행한다.
