# Kubebuilder Basic Flow

Kubebuilder 기반 Operator 개발의 기본 순서는 요구사항을 구조화한 뒤 프로젝트 scaffold를 만들고, API 타입과 Controller를 보정한 다음 검증 명령을 실행하는 흐름이다.

일반적인 단계:

1. `kubebuilder init`으로 Operator 프로젝트 기본 구조와 Go module을 생성한다.
2. `kubebuilder create api --group <group> --version <version> --kind <Kind> --resource --controller`로 CRD 타입과 Controller scaffold를 만든다.
3. `api/<version>/*_types.go`에 spec/status 필드를 반영한다.
4. `config/samples`에 Custom Resource 예시를 작성한다.
5. `make generate`로 deepcopy 코드를 생성한다.
6. `make manifests`로 CRD/RBAC manifest를 생성한다.
7. `make test`로 Go 테스트와 기본 컴파일을 확인한다.

Agent 관점에서는 이 문서를 사용해 자연어 요구사항이 Kubebuilder 생성 흐름에 필요한 정보를 충분히 포함하는지 확인한다.

