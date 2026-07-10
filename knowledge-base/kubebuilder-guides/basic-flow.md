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

Agent 자동화 흐름에서는 이 기본 절차가 다음 Tool 순서로 표현된다.

1. `spec_generator`: 자연어 요구사항을 `operator-spec.yaml` 구조화 계약으로 변환한다.
2. `command_planner`: 생성된 스펙을 사람이 검토할 수 있는 Kubebuilder 실행 계획으로 정리한다.
3. `scaffold_runner`: Kubebuilder scaffold를 dry-run 또는 승인된 execute 모드로 실행한다.
4. `artifact_patcher`: API 타입, sample YAML, RBAC marker, Controller 코드를 보정한다.
5. `validation`: `make generate`, `make manifests`, `make test`를 실행해 산출물을 검증한다.
