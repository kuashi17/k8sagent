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

사례:

- Go `1.26.3` 환경에서 Kubebuilder v4.1.1 기본값인 `controller-tools v0.15.0` 설치가 실패할 수 있습니다.
- 이 경우 `Makefile`의 `CONTROLLER_TOOLS_VERSION`을 Go 버전과 호환되는 버전으로 상향합니다.
- RedisCache MVP에서는 `controller-tools v0.21.0`으로 상향하여 `controller-gen object`와 `controller-gen crd` 생성을 통과했습니다.

권장 조치:

```bash
go list -m -versions sigs.k8s.io/controller-tools
go install sigs.k8s.io/controller-tools/cmd/controller-gen@v0.21.0
controller-gen --version
```

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

### 네트워크 제한 환경 오류

확인 항목:

- Go dependency, GitHub 원격 YAML, 컨테이너 이미지 다운로드가 필요한 명령인지 확인합니다.
- 샌드박스 또는 사내망 DNS 제한으로 실패한 것인지 확인합니다.
- e2e 테스트가 원격 manifest를 가져오는지 확인합니다.

사례:

- Kubebuilder 기본 e2e 테스트는 Prometheus Operator와 cert-manager 원격 YAML을 GitHub에서 가져오므로, 네트워크 제한 환경에서는 `go test ./...`가 실패할 수 있습니다.
- 1차 MVP의 scaffold 검증에서는 e2e를 제외하고 `go test ./api/... ./cmd/... ./test/utils`로 기본 컴파일 검증을 수행합니다.
