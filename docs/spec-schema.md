# Operator 스펙 구조

## 역할

`operator-spec.yaml`은 사용자의 요구사항을 Kubebuilder와 Controller 생성 Tool이 사용할 수 있도록 정규화한 중간 데이터 구조입니다. 자연어 원문이나 LLM 계획을 코드 생성기가 직접 읽지 않게 하고, 이후 단계의 입력 형식을 이 스펙으로 고정합니다.

```text
사용자 요구사항
  → operator-spec.yaml
  → ControllerGenerationIR
  → Controller · API 타입 · RBAC · CRD
```

현재 스펙은 `agent/tools/spec_generator.py`가 생성합니다. `artifact_patcher.py`는 이 스펙을 내부 모델로 정규화하고, `controller_pipeline.py`는 정규화된 값을 Controller IR로 변환합니다.

## 최상위 구조

스펙 생성기는 다음 키를 항상 출력합니다. 값이 비어 있거나 유효하지 않으면 `errors`에 원인이 기록되고 다음 생성 단계가 중단됩니다.

| 필드 | 역할 |
| --- | --- |
| `metadata` | 입력 파일, 생성 시각과 generator 버전 |
| `project` | Kubebuilder 프로젝트 이름, domain과 Go module |
| `api` | Custom Resource의 group, version과 kind |
| `specFields` | 사용자가 입력할 원하는 상태 필드 |
| `statusFields` | Controller가 기록할 실제 상태 필드 |
| `controller` | 관리·관찰 리소스, 매핑과 lifecycle 정책 |
| `rbac.resources` | Custom Resource와 Kubernetes 리소스 권한 |
| `validation.commands` | 생성 후 실행할 make 검증 |
| `sampleDefaults` | 샘플 Custom Resource에 사용할 선택적 기본값 |
| `warnings` | 생성은 가능하지만 사용자가 확인할 내용 |
| `errors` | 다음 단계로 진행할 수 없는 형식 또는 필수 정보 오류 |

## Metadata와 Project

```yaml
metadata:
  sourceFile: requirements/customer-portal.txt
  generatedAt: "2026-07-17T10:30:00+09:00"
  generatorVersion: 0.1.0
project:
  name: customer-portal-operator
  domain: sample.io
  module: sample.io/customer-portal-operator
```

`project.name`과 `project.module`은 Custom Resource kind와 domain에서 생성합니다. 프로젝트 이름은 Kubernetes DNS 이름 길이를 넘지 않도록 필요한 경우 축약됩니다.

## Custom Resource API

```yaml
api:
  domain: sample.io
  group: apps
  version: v1alpha1
  kind: CustomerPortal
```

사용자가 `apps.sample.io/v1alpha1`처럼 API를 입력하면 다음과 같이 분리합니다.

- group: `apps`
- domain: `sample.io`
- version: `v1alpha1`

group, domain, version과 kind는 Kubebuilder API 생성에 필요한 필수 값입니다.

## spec/status 필드

```yaml
specFields:
  - name: image
    type: string
    description: 실행할 컨테이너 이미지
    typeInferred: false
    needsConfirmation: false
statusFields:
  - name: readyReplicas
    type: int32
    description: 준비된 Pod 개수
    typeInferred: false
    needsConfirmation: false
```

각 필드는 다음 정보를 가집니다.

| 필드 | 의미 |
| --- | --- |
| `name` | JSON과 Go struct에서 사용할 필드 이름 |
| `type` | 정규화된 Go 필드 타입 |
| `description` | 필드 용도와 생성 코드 주석 |
| `typeInferred` | 명시적 타입이 없어 이름과 설명에서 제안했는지 여부 |
| `needsConfirmation` | 실행 전에 정확한 타입을 사용자에게 확인해야 하는지 여부 |

지원 타입:

```text
string, int32, int64, bool,
[]string, map[string]string,
metav1.Time, []metav1.Condition
```

`int`는 `int32`, `boolean`은 `bool`로 정규화합니다. 타입을 확정할 수 없으면 빈 타입과 `needsConfirmation: true`를 기록하며, `INVALID_FIELD_TYPE` 또는 추가 정보 요청으로 다음 단계 실행을 차단합니다.

## Controller 구조

```yaml
controller:
  enabled: true
  managedResources:
    - Deployment
  observedResources: []
  resourcePolicies:
    - kind: Deployment
      strategy: create-or-update
      ownership: ownerReference
      deletionPolicy: garbage-collect
  responsibilities:
    - Deployment를 생성하고 변경을 반영한다
    - 외부 변경을 CustomerPortal spec 기준으로 복구한다
  fieldMappings:
    - from: spec.image
      to: Deployment.container.image
    - from: spec.replicas
      to: Deployment.replicas
  statusRules:
    - Deployment.status.readyReplicas를 status.readyReplicas에 기록한다
```

| 필드 | 의미 |
| --- | --- |
| `managedResources` | Controller가 생성하거나 변경하는 Kubernetes 리소스 |
| `observedResources` | 생성·변경하지 않고 상태만 읽는 리소스 |
| `resourcePolicies` | 리소스별 변경, 소유권과 삭제 정책 |
| `responsibilities` | 요구사항에서 추출한 Controller 책임 |
| `fieldMappings` | spec 값이 반영될 Kubernetes 필드 |
| `statusRules` | status 값의 출처와 갱신 규칙 |

리소스 정책 조합:

| 목적 | `strategy` | `ownership` | `deletionPolicy` |
| --- | --- | --- | --- |
| 생성하고 함께 삭제 | `create-or-update` | `ownerReference` | `garbage-collect` |
| 생성하지만 삭제 후 유지 | `create-or-update` | `none` | `retain` |
| 기존 리소스 읽기 전용 | `read-only` | `none` | `retain` |

읽기 전용 리소스는 `observedResources`에 기록되고 쓰기 RBAC을 갖지 않습니다. 유지와 함께 삭제처럼 서로 모순되는 정책은 `errors`에 기록합니다.

## RBAC 구조

```yaml
rbac:
  resources:
    - apiGroup: apps.sample.io
      resource: customerportals
      verbs: [get, list, watch, update, patch]
    - apiGroup: apps
      resource: deployments
      verbs: [get, list, watch, create, update, patch, delete]
```

RBAC은 관리·관찰 리소스의 동작에서 계산합니다.

- 관리 리소스: 조회와 생성·변경·삭제 권한
- 관찰 리소스: `get`, `list`, `watch`만 허용
- Custom Resource status: 내부 정규화 단계에서 status 갱신 권한 보완
- wildcard 요청: 그대로 사용하지 않고 최소 권한 규칙으로 대체

raw spec은 `rbac.resources`를 사용합니다. Artifact Patcher가 이를 내부 `rbacResources`로 정규화하고 중복 제거와 status 권한 보완을 수행합니다. Controller Renderer는 원본 RBAC 문장을 직접 해석하지 않습니다.

## Validation과 Sample

요구사항에 별도 검증 명령이 없으면 다음 기본값을 적용합니다.

```yaml
validation:
  commands:
    - make generate
    - make manifests
    - make test
```

실행 엔진은 허용된 make target만 실행합니다. LLM이 임의의 검증 명령을 추가할 수 없습니다.

샘플 Custom Resource 값을 명시한 경우 `sampleDefaults`에 저장합니다.

```yaml
sampleDefaults:
  image: nginx:latest
  replicas: 2
```

값을 작성하지 않으면 Artifact Patcher가 필드 타입과 이름에 맞는 안전한 샘플 값을 생성합니다.

## Warnings와 Errors

```yaml
warnings: []
errors: []
```

`warnings`는 일부 정보 추론 실패, 샘플 값 해석 실패, wildcard RBAC 대체처럼 사용자가 확인해야 하지만 스펙 파일에는 기록할 수 있는 항목입니다. `errors`는 필수 값 누락, 필드 타입 미확정이나 모순된 lifecycle처럼 다음 생성을 중단해야 하는 항목입니다.

다음 항목은 생성 전에 유효해야 합니다.

- `project.name`, `project.domain`, `project.module`
- `api.group`, `api.version`, `api.kind`
- 하나 이상의 `specFields`와 `statusFields`
- 모든 spec/status 필드의 확정된 타입
- 서로 충돌하지 않는 리소스 정책

## 생성 경계

이 스펙은 신규 Controller 생성 경로의 기준입니다. 호환용 입력이 사용되면 Artifact Patcher가 먼저 내부 모델로 정규화하며, Controller Renderer는 원본 요구사항이나 이전 설정을 직접 참조하지 않습니다. Capability별 예외는 Renderer가 아니라 Adapter와 Validation Policy에서 처리합니다.
