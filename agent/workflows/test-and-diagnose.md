# Test and Diagnose Workflow

## 목적

Kubebuilder 프로젝트의 테스트 실행과 실패 로그 분석 절차를 정의합니다.

## 흐름

1. 테스트 실행 전 dependency 상태를 확인합니다.
2. `make test`를 실행합니다.
3. 테스트 결과 로그를 저장합니다.
4. 실패한 패키지와 테스트 케이스를 확인합니다.
5. 오류 유형을 분류합니다.
6. 원인 후보와 수정 방향을 제시합니다.
7. 필요한 경우 특정 산출물만 부분 수정 또는 재생성합니다.

## 오류 분류 예시

- 컴파일 오류
- envtest 설정 오류
- Reconcile 로직 오류
- CRD schema 오류
- RBAC 권한 오류
- 테스트 fixture 오류

