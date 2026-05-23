# Validation Flow

## 목적

이 문서는 Kubebuilder 기반 Operator 프로젝트에서 수행해야 하는 기본 검증 흐름을 정의합니다.

## 기본 검증 명령

| 명령 | 목적 |
| --- | --- |
| `make generate` | DeepCopy 등 생성 코드 갱신 |
| `make manifests` | CRD, RBAC, Webhook 등 Kubernetes manifest 생성 |
| `make test` | Go 테스트 및 envtest 기반 Controller 테스트 실행 |

## 검증 순서

1. Kubebuilder 프로젝트 루트로 이동합니다.
2. `go mod tidy` 필요 여부를 확인합니다.
3. `make generate`를 실행합니다.
4. `make manifests`를 실행합니다.
5. `make test`를 실행합니다.
6. 각 단계의 로그를 저장합니다.
7. 실패 시 실패 단계와 오류 유형을 분류합니다.

## 성공 기준

- 생성 명령이 exit code 0으로 종료됩니다.
- `api` 패키지의 DeepCopy 코드가 정상 생성됩니다.
- `config/crd`, `config/rbac` 산출물이 정상 갱신됩니다.
- 테스트가 실패 없이 완료됩니다.

## 실패 시 수집 정보

- 실패한 명령
- exit code
- 표준 출력
- 표준 오류
- 관련 파일 경로
- 직전 변경 내용
- 도구 버전

