# Troubleshooting Guide

## 목적

이 문서는 Kubebuilder 기반 Operator 개발 중 자주 발생하는 오류 유형과 확인 방향을 정리합니다.

## 오류 유형

### go module 오류

확인 항목:

- `go.mod` module path가 올바른지 확인합니다.
- 필요한 dependency가 누락되지 않았는지 확인합니다.
- `go mod tidy` 실행이 필요한지 확인합니다.

### controller-gen 오류

확인 항목:

- `controller-gen` 바이너리가 설치되어 있는지 확인합니다.
- Kubebuilder와 controller-tools 버전 호환성을 확인합니다.
- API 타입 주석과 marker 형식이 올바른지 확인합니다.
- CRD schema로 변환할 수 없는 Go 타입이 있는지 확인합니다.

### CRD schema 오류

확인 항목:

- `Spec`와 `Status` 필드가 JSON 직렬화 가능한지 확인합니다.
- 필드 태그가 올바른지 확인합니다.
- optional/required marker가 의도와 일치하는지 확인합니다.

### RBAC 오류

확인 항목:

- Controller에서 접근하는 리소스와 RBAC marker가 일치하는지 확인합니다.
- apiGroups, resources, verbs 범위가 충분한지 확인합니다.
- 과도한 cluster-wide 권한을 사용하고 있지 않은지 확인합니다.

### envtest 오류

확인 항목:

- envtest binary asset이 준비되어 있는지 확인합니다.
- Kubernetes API server와 etcd 테스트 바이너리 경로를 확인합니다.
- Kubebuilder 버전과 envtest 버전 호환성을 확인합니다.

### Docker/kind 오류

확인 항목:

- Docker daemon이 실행 중인지 확인합니다.
- kind 클러스터가 정상 생성되었는지 확인합니다.
- 이미지 로드 또는 네트워크 문제가 있는지 확인합니다.

