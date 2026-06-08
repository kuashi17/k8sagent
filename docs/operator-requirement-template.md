# Operator Requirement Template

## 목적

이 문서는 Kubebuilder 기반 Kubernetes Operator 요구사항을 특정 예시에 종속되지 않는 공통 형식으로 작성하기 위한 템플릿입니다.

작성된 요구사항은 AI Agent가 구조화 스펙 YAML로 변환하고, 이후 Kubebuilder scaffold 생성, 산출물 생성, 검증, 오류 분석 단계로 넘기는 입력으로 사용합니다.

## 공통 항목

| 항목 | 설명 | 구조화 스펙 매핑 |
| --- | --- | --- |
| 리소스 목적 | Operator가 관리하려는 업무 대상과 목적 | `controller.responsibilities` 참고 정보 |
| domain | Kubernetes API domain | `project.domain`, `api.domain` |
| group | Kubernetes API group | `api.group` |
| version | Kubernetes API version | `api.version` |
| kind | Custom Resource Kind | `api.kind` |
| spec 필드 목록 | 사용자가 선언하는 원하는 상태 | `specFields` |
| status 필드 목록 | Controller가 기록하는 관찰 상태 | `statusFields` |
| 감지할 변경 | Controller가 watch/reconcile해야 하는 변경 | `controller.responsibilities` |
| 관리 리소스 | Controller가 생성/수정/삭제할 Kubernetes 리소스 | `controller.managedResources` |
| Reconcile 책임 | spec 값을 리소스에 반영하고 상태를 맞추는 책임 | `controller.responsibilities` |
| RBAC 권한 범위 | 접근해야 하는 Kubernetes API 리소스와 동작 | `rbac.resources` |
| 검증 명령 | 생성 결과를 확인할 명령 | `validation.commands` |
| 샘플 Custom Resource | 사용자가 적용해볼 예시 YAML | `sample` |

## 일반 자연어 요구사항 템플릿

```text
[Kind]라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다.

이 Operator의 목적은 [리소스 목적]이다.

domain은 [domain], group은 [group], version은 [version], kind는 [kind]로 한다.

spec에는 다음 필드를 포함한다.
- [fieldName]:[type] - [description]
- [fieldName]:[type] - [description]

status에는 다음 필드를 포함한다.
- [fieldName]:[type] - [description]
- [fieldName]:[type] - [description]

Controller는 [Kind] 변경을 감지한다.
Controller는 [관리 대상 리소스]를 생성/수정/삭제한다.
Controller는 다음 규칙에 따라 spec 값을 관리 리소스에 반영한다.
- spec.[fieldName] -> [resource field]
- spec.[fieldName] -> [resource field]

Controller는 [상태 확인 대상]을 조회하여 status를 갱신한다.
- [status field]는 [갱신 기준]을 기준으로 갱신한다.
- [status field]는 [갱신 기준]을 기준으로 갱신한다.

[Kind]가 삭제되면 ownerReference 또는 finalizer 정책에 따라 하위 리소스를 정리한다.

필요한 RBAC 권한은 다음 리소스에 대한 get/list/watch/create/update/patch/delete 범위로 추론한다.
- [apiGroup/resource]
- [apiGroup/resource]

검증 명령은 다음을 사용한다.
- make generate
- make manifests
- make test
```

## RedisCache Operator 예시

```text
RedisCache라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다.

이 Operator의 목적은 Redis 캐시 인스턴스를 Kubernetes에서 선언적으로 생성하고 상태를 확인하는 것이다.

domain은 sample.io, group은 cache, version은 v1alpha1, kind는 RedisCache로 한다.

spec에는 다음 필드를 포함한다.
- size:int32 - Redis replica 수
- image:string - Redis container image
- storageSize:string - 각 Redis Pod가 사용할 PVC storage 요청량

status에는 다음 필드를 포함한다.
- phase:string - RedisCache 진행 상태
- readyReplicas:int32 - 준비된 Redis replica 수
- message:string - 상태 설명 또는 오류 메시지

Controller는 RedisCache 변경을 감지한다.
Controller는 StatefulSet, Service, PVC를 생성/수정/삭제한다.
Controller는 다음 규칙에 따라 spec 값을 관리 리소스에 반영한다.
- spec.size -> StatefulSet replicas
- spec.image -> StatefulSet container image
- spec.storageSize -> StatefulSet volumeClaimTemplates storage request

Controller는 StatefulSet 상태를 조회하여 status를 갱신한다.
- status.phase는 StatefulSet readyReplicas와 replicas 비교 결과를 기준으로 갱신한다.
- status.readyReplicas는 StatefulSet status.readyReplicas 값으로 갱신한다.
- status.message는 현재 준비 상태 또는 오류 내용을 기준으로 갱신한다.

RedisCache가 삭제되면 ownerReference에 따라 StatefulSet, Service, PVC를 정리한다.

필요한 RBAC 권한은 다음 리소스에 대해 추론한다.
- cache.sample.io/rediscaches
- apps/statefulsets
- core/services
- core/pods
- core/persistentvolumeclaims

검증 명령은 다음을 사용한다.
- make generate
- make manifests
- make test
```

## TrainingJob Operator 예시

```text
TrainingJob이라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다.

이 Operator의 목적은 GPU 학습 작업을 Kubernetes Job으로 실행하고 실행 상태를 확인하는 것이다.

domain은 ai.sample.io, group은 ml, version은 v1alpha1, kind는 TrainingJob으로 한다.

spec에는 다음 필드를 포함한다.
- image:string - 학습 컨테이너 image
- gpuCount:int32 - 요청할 GPU 개수
- pvcName:string - 학습 데이터와 결과 경로를 제공할 PVC 이름
- datasetPath:string - 입력 데이터 경로
- outputPath:string - 결과 저장 경로

status에는 다음 필드를 포함한다.
- phase:string - 학습 작업 진행 상태
- jobName:string - 생성된 Kubernetes Job 이름
- podName:string - 실행 중인 Pod 이름
- message:string - 상태 설명 또는 오류 메시지

Controller는 TrainingJob 변경을 감지한다.
Controller는 Kubernetes Job과 관련 Pod 상태를 관리한다.
Controller는 다음 규칙에 따라 spec 값을 관리 리소스에 반영한다.
- spec.image -> Job container image
- spec.gpuCount -> Job container resources.limits["nvidia.com/gpu"]
- spec.pvcName -> Job Pod volume PVC claimName
- spec.datasetPath -> Job container environment variable DATASET_PATH
- spec.outputPath -> Job container environment variable OUTPUT_PATH

Controller는 Job과 Pod 상태를 조회하여 status를 갱신한다.
- status.phase는 Job condition과 Pod phase를 기준으로 갱신한다.
- status.jobName은 생성된 Job 이름으로 갱신한다.
- status.podName은 Job이 생성한 Pod 이름으로 갱신한다.
- status.message는 성공, 진행 중, 실패 원인을 기준으로 갱신한다.

TrainingJob이 삭제되면 ownerReference 또는 finalizer 정책에 따라 Job을 정리한다.

필요한 RBAC 권한은 다음 리소스에 대해 추론한다.
- ml.ai.sample.io/trainingjobs
- batch/jobs
- core/pods
- core/persistentvolumeclaims

검증 명령은 다음을 사용한다.
- make generate
- make manifests
- make test
```

## 구조화 스펙 변환 기준

| 자연어 요구사항 | 구조화 스펙 필드 |
| --- | --- |
| `domain은 sample.io` | `project.domain`, `api.domain` |
| `group은 cache` | `api.group` |
| `version은 v1alpha1` | `api.version` |
| `kind는 RedisCache` | `api.kind` |
| `spec에는 size:int32` | `specFields[].name`, `specFields[].type` |
| `status에는 phase:string` | `statusFields[].name`, `statusFields[].type` |
| `Controller는 ... 변경을 감지한다` | `controller.responsibilities` |
| `StatefulSet, Service를 생성한다` | `controller.managedResources` |
| `spec.size -> StatefulSet replicas` | `controller.fieldMappings` |
| `StatefulSet 상태를 조회하여 status 갱신` | `controller.statusRules` |
| `필요한 RBAC 권한` | `rbac.resources` |
| `make generate` | `validation.commands` |

## 작성 시 주의사항

- 필드 타입을 명확히 작성합니다. 예: `size:int32`, `image:string`, `enabled:bool`.
- Controller가 실제로 생성하거나 관리할 Kubernetes 리소스를 명확히 작성합니다.
- spec 값이 생성 리소스의 어느 필드에 반영되는지 작성합니다.
- status가 어떤 기준으로 갱신되는지 작성합니다.
- RBAC 권한을 추론할 수 있도록 관리 대상 리소스를 빠뜨리지 않습니다.
- 처음에는 하나의 핵심 리소스를 관리하는 Operator부터 작성합니다.
- Webhook, finalizer, 외부 API 연계, 복잡한 상태 전이는 기본 흐름이 검증된 뒤 추가합니다.
