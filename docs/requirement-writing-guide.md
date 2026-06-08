# Requirement Writing Guide

## 목적

이 문서는 사용자가 Operator 요구사항을 자연어로 작성할 때 어떤 내용을 포함해야 하는지 안내합니다.

목표는 사용자가 Kubebuilder, CRD, Reconcile, RBAC 용어를 완벽히 몰라도 AI Agent가 구조화 스펙으로 변환할 수 있을 만큼 충분한 정보를 제공하도록 돕는 것입니다.

## 작성 흐름

요구사항은 다음 순서로 작성합니다.

```text
관리 목적
-> API 메타정보
-> 사용자가 입력할 값
-> 사용자가 보고 싶은 상태
-> Controller가 관리할 Kubernetes 리소스
-> spec 값과 리소스 필드 매핑
-> status 갱신 기준
-> 삭제/정리 정책
-> 검증 명령
```

## 1. 리소스 목적 작성

Operator가 무엇을 관리하는지 먼저 씁니다.

좋은 예:

```text
RedisCache라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다.
이 Operator의 목적은 Redis 캐시 인스턴스를 Kubernetes에서 선언적으로 생성하고 상태를 확인하는 것이다.
```

부족한 예:

```text
Redis Operator를 만들고 싶다.
```

부족한 이유:

- 어떤 Custom Resource 이름을 쓸지 불명확합니다.
- Redis를 어떤 Kubernetes 리소스로 만들지 추론하기 어렵습니다.

## 2. API 메타정보 작성

domain, group, version, kind를 명확히 씁니다.

좋은 예:

```text
domain은 sample.io, group은 cache, version은 v1alpha1, kind는 RedisCache로 한다.
```

주의사항:

- `domain`은 DNS domain 형식으로 씁니다. 예: `sample.io`, `ai.sample.io`
- `group`은 영문 소문자, 숫자, `-`만 사용합니다. 예: `cache`, `ml`, `backup`
- `version`은 Kubernetes API version 형식으로 씁니다. 예: `v1alpha1`, `v1beta1`, `v1`
- `kind`는 CamelCase로 씁니다. 예: `RedisCache`, `TrainingJob`

## 3. spec 필드 작성

`spec`은 사용자가 Custom Resource를 만들 때 입력하는 원하는 상태입니다.

형식:

```text
- [fieldName]:[type] - [description]
```

예:

```text
spec에는 다음 필드를 포함한다.
- size:int32 - Redis replica 수
- image:string - Redis container image
- storageSize:string - 각 Redis Pod가 사용할 PVC storage 요청량
```

자주 쓰는 타입:

| 타입 | 의미 |
| --- | --- |
| `string` | 문자열 |
| `int32` | 정수 |
| `bool` | true/false |
| `[]string` | 문자열 목록 |

주의사항:

- 필드 타입을 생략하지 않습니다.
- `size`, `image`, `storageSize`처럼 JSON field name으로 쓸 수 있는 이름을 사용합니다.
- 한 필드에 여러 의미를 섞지 않습니다.

## 4. status 필드 작성

`status`는 Controller가 관찰한 현재 상태입니다.

예:

```text
status에는 다음 필드를 포함한다.
- phase:string - 진행 상태
- readyReplicas:int32 - 준비된 replica 수
- message:string - 상태 설명 또는 오류 메시지
```

좋은 status 필드는 사용자가 `kubectl get -o yaml`로 봤을 때 현재 상황을 이해하게 해줍니다.

자주 쓰는 status:

| 필드 | 의미 |
| --- | --- |
| `phase` | Pending, Progressing, Ready, Failed 같은 상태 |
| `message` | 상태 설명 또는 오류 메시지 |
| `readyReplicas` | 준비된 replica 수 |
| `jobName` | 생성된 Job 이름 |
| `podName` | 관련 Pod 이름 |
| `lastRunTime` | 마지막 실행 시간 |

## 5. Controller가 관리할 리소스 작성

Controller가 어떤 Kubernetes 리소스를 만들거나 관리해야 하는지 씁니다.

예:

```text
Controller는 RedisCache 변경을 감지한다.
Controller는 StatefulSet, Service, PVC를 생성/수정/삭제한다.
```

다른 예:

```text
Controller는 TrainingJob 변경을 감지한다.
Controller는 Kubernetes Job과 관련 Pod 상태를 관리한다.
```

주의사항:

- `리소스를 만든다`고만 쓰지 말고 구체적인 Kubernetes 리소스 이름을 씁니다.
- 예: `Deployment`, `StatefulSet`, `Service`, `Job`, `CronJob`, `ConfigMap`, `Secret`, `PVC`

## 6. spec-to-resource 매핑 작성

사용자가 입력한 spec 값이 생성 리소스의 어디에 반영되는지 씁니다.

예:

```text
Controller는 다음 규칙에 따라 spec 값을 관리 리소스에 반영한다.
- spec.size -> StatefulSet replicas
- spec.image -> StatefulSet container image
- spec.storageSize -> StatefulSet volumeClaimTemplates storage request
```

TrainingJob 예:

```text
- spec.image -> Job container image
- spec.gpuCount -> Job container resources.limits["nvidia.com/gpu"]
- spec.pvcName -> Job Pod volume PVC claimName
- spec.datasetPath -> Job container environment variable DATASET_PATH
- spec.outputPath -> Job container environment variable OUTPUT_PATH
```

이 정보가 있어야 AI Agent가 Controller 코드를 생성할 수 있습니다.

## 7. status 갱신 기준 작성

Controller가 어떤 기준으로 status를 채워야 하는지 씁니다.

예:

```text
Controller는 StatefulSet 상태를 조회하여 status를 갱신한다.
- status.phase는 StatefulSet readyReplicas와 replicas 비교 결과를 기준으로 갱신한다.
- status.readyReplicas는 StatefulSet status.readyReplicas 값으로 갱신한다.
- status.message는 현재 준비 상태 또는 오류 내용을 기준으로 갱신한다.
```

부족한 예:

```text
status를 갱신한다.
```

부족한 이유:

- 어떤 리소스를 조회해야 하는지 알 수 없습니다.
- 어떤 조건에서 Ready/Failed가 되는지 알 수 없습니다.

## 8. 삭제/정리 정책 작성

Custom Resource가 삭제될 때 하위 리소스를 어떻게 정리할지 씁니다.

예:

```text
RedisCache가 삭제되면 ownerReference에 따라 StatefulSet, Service, PVC를 정리한다.
```

또는:

```text
외부 리소스 정리가 필요하므로 finalizer를 사용한다.
```

기준:

- Kubernetes 내부 리소스만 정리하면 보통 `ownerReference`를 우선 고려합니다.
- 외부 API, 외부 저장소, 클라우드 리소스 정리가 필요하면 `finalizer`가 필요할 수 있습니다.

## 9. RBAC 권한 범위 작성

관리 대상 리소스를 쓰면 Agent가 RBAC를 추론할 수 있습니다.

예:

```text
필요한 RBAC 권한은 다음 리소스에 대해 추론한다.
- cache.sample.io/rediscaches
- apps/statefulsets
- core/services
- core/pods
- core/persistentvolumeclaims
```

주의사항:

- Controller가 조회만 하는 리소스와 생성/수정/삭제하는 리소스를 구분하면 더 좋습니다.
- 처음에는 `get/list/watch/create/update/patch/delete` 범위로 시작하고, 이후 줄일 수 있습니다.

## 10. 검증 명령 작성

기본 검증 명령은 다음을 사용합니다.

```text
검증 명령은 다음을 사용한다.
- make generate
- make manifests
- make test
```

kind 클러스터까지 확인하려면 다음 흐름을 추가할 수 있습니다.

```text
- make install
- kubectl apply -f config/samples/<sample>.yaml
- kubectl get <custom-resource>
- kubectl get <managed-resource>
```

## workspace 경로 이해하기

`project.workspace`는 스펙에 기록되는 기본 프로젝트 경로입니다.

실제 scaffold 실행에서는 `scaffold_runner.py --workspace` 값을 "생성 위치의 상위 폴더"로 사용할 수 있습니다. 이 경우 최종 생성 위치는 `--workspace` 아래에 프로젝트 디렉터리명을 붙인 경로가 됩니다.

예:

```text
Spec-defined workspace: workspace/app-config-operator
Scaffold workspace parent: workspace/generated-operators
Final target project directory: workspace/generated-operators/app-config-operator
```

초보자는 command plan과 scaffold dry-run에 표시되는 `Final target project directory` 또는 `Target project directory`를 실제 생성될 디렉터리로 보면 됩니다.

## 구조화 스펙 변환 기준

| 요구사항 표현 | 구조화 스펙 |
| --- | --- |
| 리소스 목적 | `controller.responsibilities` 참고 정보 |
| domain | `project.domain`, `api.domain` |
| group | `api.group` |
| version | `api.version` |
| kind | `api.kind` |
| spec 필드 | `specFields` |
| status 필드 | `statusFields` |
| 변경 감지 대상 | `controller.responsibilities` |
| 관리 대상 리소스 | `controller.managedResources`, `rbac.resources` |
| spec-to-resource 매핑 | `controller.fieldMappings` |
| status 갱신 기준 | `controller.statusRules` |
| 검증 명령 | `validation.commands` |
| 샘플 CR | `sample` |

## 작성 체크리스트

- [ ] Operator가 관리할 대상과 목적을 썼다.
- [ ] domain, group, version, kind를 명확히 썼다.
- [ ] spec 필드마다 타입과 설명을 썼다.
- [ ] status 필드마다 타입과 설명을 썼다.
- [ ] Controller가 관리할 Kubernetes 리소스를 명확히 썼다.
- [ ] spec 값이 리소스에 어떻게 반영되는지 썼다.
- [ ] status 갱신 기준을 썼다.
- [ ] 삭제 시 하위 리소스 정리 방식을 썼다.
- [ ] RBAC 추론에 필요한 리소스 목록을 썼다.
- [ ] 검증 명령을 썼다.

## 처음 작성할 때의 권장 범위

처음에는 너무 많은 기능을 넣지 않습니다.

권장:

- 하나의 Custom Resource
- 하나 또는 두 개의 핵심 Kubernetes 리소스
- 명확한 spec 필드
- 단순한 status 갱신
- ownerReference 기반 정리

나중에 추가:

- Webhook validation/defaulting
- 복잡한 finalizer
- 외부 API 연계
- 여러 리소스 간 복잡한 상태 전이
- GitHub/Jenkins/Harbor/Argo CD 자동 연계
