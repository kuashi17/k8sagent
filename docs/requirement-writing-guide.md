# Operator 요구사항 작성 가이드

이 문서는 k8sagent가 일관된 Operator 계획을 만들 수 있도록 요구사항에 포함할 정보를 설명합니다. Kubernetes와 Kubebuilder의 모든 용어를 알 필요는 없지만, 아래 네 가지 정보는 가능한 한 명확하게 작성하는 것이 좋습니다.

## 필요한 정보 4가지

| 정보 | 필요한 이유 | 간단한 예 |
| --- | --- | --- |
| Custom Resource 이름과 API | 생성할 CRD와 Go API 패키지를 결정 | `CustomerPortal`, `apps.sample.io/v1alpha1` |
| spec/status 필드와 타입 | 사용자가 입력할 값과 Controller가 기록할 상태를 정의 | `image: string`, `readyReplicas: int32` |
| 관리 대상과 동작 | Reconcile 코드와 필요한 권한을 결정 | Deployment 생성·변경·drift 복구 |
| 삭제 방식 | Custom Resource 삭제 후 하위 리소스 처리 방법을 결정 | Deployment도 함께 삭제, 기존 PVC는 유지 |

요구사항은 자유로운 문장으로 작성할 수 있습니다. 다만 이름, 타입과 관리 대상이 빠지면 Agent가 임의로 확정하지 않고 코드 생성 전에 필요한 내용을 질문합니다.

## 1. Custom Resource 이름과 API

Custom Resource 이름은 사용자가 `kubectl`로 생성하고 조회할 리소스의 종류입니다.

```text
Custom Resource 이름은 CustomerPortal입니다.
API는 apps.sample.io/v1alpha1입니다.
```

`apps.sample.io/v1alpha1`은 이 Custom Resource를 Kubernetes에서 구분하기 위한 API 주소입니다.

- `apps`: API group
- `sample.io`: 프로젝트나 조직을 구분하는 domain
- `v1alpha1`: API version

예제의 `sample.io`는 실제 프로젝트에서 사용하는 고유한 domain으로 바꿀 수 있습니다. Custom Resource 이름은 `CustomerPortal`, `ScheduledTask`처럼 CamelCase로 작성하는 것을 권장합니다.

## 2. spec과 status 필드

`spec`은 사용자가 원하는 상태를 입력하는 곳이고, `status`는 Controller가 확인한 실제 상태를 기록하는 곳입니다.

```text
spec:
- image: string
- replicas: int32

status:
- phase: string
- readyReplicas: int32
- message: string
```

자주 사용하는 타입은 다음과 같습니다.

| 타입 | 입력 예 |
| --- | --- |
| `string` | 이미지, 이름, 경로 |
| `int32`, `int64` | replicas, port, 보관 일수 |
| `bool` | 기능 활성화 여부 |
| `[]string` | 명령어나 이름 목록 |
| `map[string]string` | label, ConfigMap data |
| `metav1.Time` | 마지막 실행 시각 |

필드 이름만 있고 타입이 없으면 Agent가 일반적인 타입을 제안할 수 있지만, 실행 전 사용자 확인이 필요할 수 있습니다. `숫자 타입`, `사용자 정의 타입`처럼 범위가 불명확한 표현은 정확한 타입을 다시 질문합니다.

## 3. 관리 대상과 동작

Controller가 어떤 Kubernetes 리소스를 다루고 무엇을 해야 하는지 작성합니다.

```text
Controller는 Deployment를 생성하고 관리합니다.
spec.image와 spec.replicas 변경을 Deployment에 반영합니다.
Deployment가 직접 수정되면 Custom Resource의 spec 기준으로 복구합니다.
```

가능하면 다음 내용을 구분해 작성합니다.

- 생성·변경할 리소스: `Deployment`, `Service`, `ConfigMap`, `Job` 등
- 읽기만 할 리소스: 기존 Deployment나 Job이 만든 Pod 등
- 변경 반영: 어떤 spec 필드를 어느 리소스에 반영할지
- status 출처: 어떤 리소스의 상태를 어떤 status 필드에 기록할지
- 외부 변경 복구: 직접 수정된 관리 리소스를 spec 기준으로 되돌릴지

읽기 전용 요구사항은 쓰기 동작과 명확히 구분합니다.

```text
기존 Deployment를 읽기만 합니다.
Deployment를 생성하거나 수정하거나 삭제하면 안 됩니다.
Deployment의 replicas와 readyReplicas를 Custom Resource status에 기록합니다.
```

특정 리소스를 제외해야 한다면 명시적으로 작성할 수 있습니다.

```text
NetworkPolicy만 관리합니다.
Deployment, Service와 Pod는 생성하지 마세요.
```

k8sagent는 제외된 리소스를 다른 관리 대상으로 임의 선택하지 않습니다. 요청한 Kubernetes 리소스가 지원되지 않으면 비슷한 리소스로 대체하지 않고 제한사항이나 추가 확인이 필요하다고 안내합니다.

## 4. 삭제 방식

Custom Resource를 삭제할 때 관리 리소스를 함께 삭제할지 유지할지 작성합니다.

함께 삭제하는 예:

```text
CustomerPortal이 삭제되면 생성한 Deployment도 함께 삭제합니다.
```

기존 리소스를 유지하는 예:

```text
DeploymentHealth가 삭제되어도 관찰하던 기존 Deployment는 유지합니다.
```

```text
DataVolume이 삭제되어도 데이터 보호를 위해 PVC는 유지합니다.
```

`유지해야 한다`와 `함께 삭제해야 한다`처럼 서로 반대되는 요구사항을 동시에 작성하면 Agent는 어느 쪽도 임의 선택하지 않고 삭제 방식을 다시 질문합니다.

## 정확도를 높이는 선택 정보

다음 내용은 필수는 아니지만 복잡한 Controller를 만들 때 도움이 됩니다.

- spec 필드가 관리 리소스의 어느 값에 반영되는지
- status 필드가 어떤 Kubernetes 상태에서 계산되는지
- 읽기 전용 관찰 리소스와 직접 관리 리소스의 구분
- 외부 변경을 복구해야 하는 필드
- 변경할 수 없는 필드가 있을 때 원하는 처리 방법
- 생성하지 않아야 하는 Kubernetes 리소스

RBAC verb, Kubebuilder 명령, workspace 경로는 직접 작성하지 않아도 됩니다. k8sagent가 관리·관찰 동작을 기준으로 최소 권한을 계산하고, 생성 후 `make generate`, `make manifests`, `make test`를 수행합니다.

## 완성 예시

```text
CustomerPortal Operator를 만들어 주세요.
API는 apps.sample.io/v1alpha1입니다.

spec:
- image: string
- replicas: int32

status:
- phase: string
- readyReplicas: int32
- message: string

Controller는 Deployment를 생성하고 관리합니다.
spec.image와 spec.replicas 변경을 Deployment에 반영합니다.
Deployment가 직접 수정되면 CustomerPortal spec 기준으로 복구합니다.
Deployment의 status.readyReplicas를 CustomerPortal의 status.readyReplicas에 기록합니다.
CustomerPortal이 삭제되면 생성한 Deployment도 함께 삭제합니다.
Service와 Pod는 직접 생성하지 마세요.
```

이 요구사항에서 Agent는 다음 내용을 확인할 수 있습니다.

- Custom Resource: `CustomerPortal`
- API: `apps.sample.io/v1alpha1`
- 입력 필드와 상태 필드
- 관리 대상: `Deployment`
- 동작: 생성, 변경 반영, drift 복구, status 갱신
- 삭제 정책: 생성한 Deployment 함께 삭제
- 제외 대상: `Service`, `Pod`

## 계획 생성 전 확인

- [ ] Custom Resource 이름과 API를 작성했는가?
- [ ] spec/status 필드에 타입을 작성했는가?
- [ ] 생성·변경할 리소스와 읽기만 할 리소스를 구분했는가?
- [ ] spec 변경과 외부 drift를 어떻게 처리할지 작성했는가?
- [ ] 삭제 시 관리 리소스를 삭제할지 유지할지 작성했는가?
- [ ] 서로 모순되는 요구사항이 없는가?

정보가 부족하거나 모순되는 경우 k8sagent는 생성 Tool을 실행하지 않습니다. 사용자가 필요한 내용을 보완한 뒤 다시 계획을 만들 수 있도록 구체적인 질문을 표시합니다.
