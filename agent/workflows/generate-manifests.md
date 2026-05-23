# Generate Manifests Workflow

## 목적

Kubebuilder 프로젝트에서 생성 코드와 Kubernetes manifest를 갱신하는 절차를 정의합니다.

## 흐름

1. 프로젝트 루트 위치를 확인합니다.
2. API 타입 정의 변경 여부를 확인합니다.
3. `make generate` 실행 목적을 확인합니다.
4. `make manifests` 실행 목적을 확인합니다.
5. 실행 결과 로그를 저장합니다.
6. 실패 시 오류 유형을 분류합니다.

## 확인 대상

- DeepCopy 생성 파일
- CRD manifest
- RBAC manifest
- Webhook manifest
- Kustomize 설정

