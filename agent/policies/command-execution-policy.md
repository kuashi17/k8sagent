# Command Execution Policy

## 목적

AI Agent가 로컬 개발환경에서 명령을 실행할 때 따라야 할 기본 원칙을 정의합니다.

## 원칙

- 명령 실행 전 실행 위치를 확인합니다.
- 프로젝트 루트와 Kubebuilder 작업 디렉터리를 구분합니다.
- 검증 명령의 목적과 예상 결과를 명확히 합니다.
- 실패 로그는 재분석 가능하도록 저장합니다.
- 파괴적인 명령은 자동 실행하지 않고 사용자 확인을 받습니다.
- 외부 시스템 연계 명령은 인증 정보와 대상 환경을 확인한 뒤 실행합니다.

## 적용 범위

현재 Agent는 로컬 생성·검증 명령을 기본 범위로 다룹니다.

- 환경 점검
- Kubebuilder scaffold 절차 확인
- `make generate`
- `make manifests`
- `make test`
- Docker/kind 기반 lifecycle 검증

외부 시스템이나 파괴적인 작업은 별도 Tool wrapper, allowlist, 사용자 승인이 추가되기 전까지 자동 실행 대상이 아닙니다.
