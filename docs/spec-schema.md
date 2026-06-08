# Operator Spec Schema

## Purpose

`operator-spec.yaml`은 자연어 Operator 요구사항을 Kubebuilder 생성 흐름에서 사용할 수 있도록 변환한 중간 스펙입니다.

현재 스펙은 규칙 기반 parser인 `agent/tools/spec_generator.py`가 생성합니다. 이후 LLM/RAG parser로 교체하더라도 이 YAML 구조를 Agent 내부 계약으로 유지하는 것을 목표로 합니다.

## Top-Level Fields

| Field | Required | Description |
| --- | --- | --- |
| `metadata` | yes | 스펙 생성 정보 |
| `project` | yes | Kubebuilder 프로젝트 정보 |
| `api` | yes | Custom Resource API 정보 |
| `specFields` | yes | CR `spec` 필드 목록 |
| `statusFields` | yes | CR `status` 필드 목록 |
| `controller` | no | Reconcile 책임과 리소스 매핑 정보 |
| `rbac` | no | Controller가 접근해야 하는 Kubernetes 리소스 |
| `validation` | no | 생성 후 실행할 검증 명령 |
| `warnings` | no | 추론이 어렵거나 기본값을 사용한 항목 |
| `errors` | no | 필수 항목 누락 등 변환 실패 사유 |

## Metadata

```yaml
metadata:
  sourceFile: requirements/my-operator.txt
  generatedAt: '2026-05-30T21:00:00+09:00'
  generatorVersion: 0.1.0
```

| Field | Description |
| --- | --- |
| `sourceFile` | 입력 요구사항 파일 경로 |
| `generatedAt` | 스펙 생성 시각 |
| `generatorVersion` | 사용한 generator 버전 |

## Project

```yaml
project:
  name: redis-cache-operator
  domain: sample.io
  module: sample.io/redis-cache-operator
```

`project.name`과 `project.module`은 기본적으로 `api.kind`와 `project.domain`에서 추론합니다.

## API

```yaml
api:
  domain: sample.io
  group: cache
  version: v1alpha1
  kind: RedisCache
```

`api.group`, `api.version`, `api.kind`는 Kubebuilder `create api` 명령의 핵심 입력입니다.

## Spec Fields

```yaml
specFields:
  - name: size
    type: int32
    description: Redis replica 수
  - name: image
    type: string
    description: Redis container image
```

지원하는 기본 타입은 `string`, `int32`, `bool`, `[]string`입니다. `int`는 `int32`, `boolean`은 `bool`로 정규화됩니다.

## Status Fields

```yaml
statusFields:
  - name: phase
    type: string
    description: 진행 상태
  - name: message
    type: string
    description: 상태 설명 또는 오류 메시지
```

`statusFields`는 Controller가 관찰한 상태를 기록하기 위한 타입 정의와 status 업데이트 로직 생성에 사용됩니다.

## Controller

```yaml
controller:
  enabled: true
  managedResources:
    - StatefulSet
    - Service
  responsibilities:
    - Controller는 RedisCache 변경을 감지한다
    - Controller는 StatefulSet, Service, PVC를 생성/수정/삭제한다
  fieldMappings:
    - from: spec.size
      to: StatefulSet replicas
  statusRules:
    - status.phase는 StatefulSet readyReplicas와 replicas 비교 결과를 기준으로 갱신한다
```

`controller.responsibilities`와 `controller.fieldMappings`는 이후 Controller/Reconcile 코드 생성 단계의 입력입니다.

## RBAC

```yaml
rbac:
  resources:
    - apiGroup: cache.sample.io
      resource: rediscaches
      verbs:
        - get
        - list
        - watch
        - update
        - patch
    - apiGroup: apps
      resource: statefulsets
      verbs:
        - get
        - list
        - watch
        - create
        - update
        - patch
        - delete
```

RBAC는 요구사항에 명시된 리소스 목록과 Controller가 관리하는 Kubernetes 리소스에서 추론합니다.

## Validation

```yaml
validation:
  commands:
    - make generate
    - make manifests
    - make test
```

요구사항에서 검증 명령을 찾지 못하면 기본값으로 `make generate`, `make manifests`, `make test`를 사용하고 `warnings`에 기록합니다.

## Warnings And Errors

```yaml
warnings:
  - validation.commands were not found; default commands were used.
errors: []
```

`warnings`는 추론은 가능하지만 사용자가 확인해야 하는 항목입니다. `errors`는 필수 항목이 누락되어 다음 생성 단계로 넘기기 어려운 항목입니다.

필수 검증 항목은 다음과 같습니다.

- `project.name`
- `project.domain`
- `project.module`
- `api.group`
- `api.version`
- `api.kind`
- `specFields`
- `statusFields`

## Example

```yaml
metadata:
  sourceFile: requirements/redis-cache.txt
  generatedAt: '2026-05-30T21:00:00+09:00'
  generatorVersion: 0.1.0
project:
  name: redis-cache-operator
  domain: sample.io
  module: sample.io/redis-cache-operator
api:
  domain: sample.io
  group: cache
  version: v1alpha1
  kind: RedisCache
specFields:
  - name: size
    type: int32
    description: Redis replica 수
statusFields:
  - name: phase
    type: string
    description: 진행 상태
controller:
  enabled: true
  managedResources:
    - StatefulSet
  responsibilities:
    - Controller는 RedisCache 변경을 감지한다
  fieldMappings:
    - from: spec.size
      to: StatefulSet replicas
  statusRules:
    - status.phase는 StatefulSet 상태를 기준으로 갱신한다
rbac:
  resources:
    - apiGroup: cache.sample.io
      resource: rediscaches
      verbs:
        - get
        - list
        - watch
        - update
        - patch
validation:
  commands:
    - make generate
    - make manifests
    - make test
warnings: []
errors: []
```
