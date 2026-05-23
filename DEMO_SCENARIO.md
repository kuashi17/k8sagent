# Demo Scenario

## 데모 목표

1차 MVP 데모의 목표는 AI Agent가 Kubebuilder 기반 Operator 개발 흐름을 단계적으로 안내하고, 로컬 환경 점검부터 검증 명령 실행 결과 분석까지 이어지는 과정을 보여주는 것입니다.

이 단계에서는 전체 자동화를 완성하기보다, 생성·검증·오류 분석 흐름이 실제 개발 절차와 연결될 수 있음을 검증합니다.

## 데모 입력 예시

```text
BackupPolicy라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다.

BackupPolicy는 대상 namespace, 스케줄, 보관 기간, 백업 대상 PVC 목록을 spec으로 가진다.
status에는 마지막 백업 시간, 성공 여부, 실패 사유를 기록한다.
Controller는 BackupPolicy 변경을 감지하고 백업 Job 생성을 조정해야 한다.
```

## 기대되는 구조화 스펙

| 항목 | 예시 |
| --- | --- |
| Resource | `BackupPolicy` |
| API Group | `backup.example.com` |
| Version | `v1alpha1` |
| Kind | `BackupPolicy` |
| Spec | `targetNamespace`, `schedule`, `retentionDays`, `pvcNames` |
| Status | `lastBackupTime`, `succeeded`, `failureReason` |
| Reconcile 책임 | BackupPolicy 감지, 백업 Job 생성, 상태 업데이트 |
| 권한 범위 | BackupPolicy, Job, PVC 조회 및 Job 생성/수정 |

## 데모 흐름

1. 사용자가 Operator 요구사항을 자연어로 입력합니다.
2. Agent가 요구사항을 구조화된 Operator 스펙으로 변환합니다.
3. Agent가 로컬 개발환경을 점검합니다.
4. Agent가 Kubebuilder scaffold 생성 절차를 안내합니다.
5. Agent가 예시 API 생성 절차를 안내합니다.
6. Agent가 CRD, Controller, RBAC, Manifest 생성 흐름을 설명합니다.
7. Agent가 `make generate` 실행 결과를 확인합니다.
8. Agent가 `make manifests` 실행 결과를 확인합니다.
9. Agent가 `make test` 실행 결과를 확인합니다.
10. 실패가 발생하면 로그를 요약하고 원인 후보와 해결 방향을 제시합니다.

## 검증 명령 예시

```text
make generate
make manifests
make test
```

## 실패 로그 분석 예시

### 상황

`make manifests` 실행 중 `controller-gen` 관련 오류가 발생합니다.

### Agent 분석 방향

- `controller-gen` 설치 여부 확인
- Kubebuilder 버전과 controller-tools 버전 호환성 확인
- API 타입 주석 형식 확인
- CRD schema로 변환할 수 없는 Go 타입 사용 여부 확인
- `go mod tidy` 필요 여부 확인

### Agent 출력 예시

```text
make manifests 단계에서 controller-gen 실행 오류가 발생했습니다.

가능한 원인:
1. controller-gen 바이너리가 설치되지 않았거나 PATH에 없습니다.
2. API 타입 정의에 CRD schema 생성이 불가능한 필드가 포함되어 있습니다.
3. Kubebuilder/controller-tools 버전 호환 문제가 있을 수 있습니다.

권장 조치:
1. make controller-gen 또는 go install로 controller-gen 설치를 확인합니다.
2. api/v1alpha1/*_types.go의 marker 주석과 필드 타입을 확인합니다.
3. go mod tidy 후 make manifests를 다시 실행합니다.
```

## 데모 성공 기준

- 요구사항이 구조화된 Operator 스펙으로 변환됩니다.
- Kubebuilder 개발 절차가 단계별로 제시됩니다.
- 검증 명령의 실행 목적과 성공 기준이 설명됩니다.
- 실패 로그가 원인 후보와 다음 조치 방향으로 요약됩니다.

