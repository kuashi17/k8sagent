# Validation and Defaulting Guide

metadata:
- source: internal-authored
- category: guide
- topic: validation defaulting

## Validation Markers

Kubebuilder validation marker는 CRD OpenAPI schema에 제약 조건을 추가한다.
예를 들어 문자열 필수값, 숫자 최소값, enum 값을 제한할 수 있다.

```go
// +kubebuilder:validation:MinLength=1
// +kubebuilder:validation:Minimum=0
```

## Defaulting

Defaulting webhook은 사용자가 생략한 값을 기본값으로 채우는 기능이다.
MVP에서는 webhook까지 자동 생성하지 않고, sample YAML과 Controller 로직에서 기본 동작을 단순하게 유지한다.

## Agent Policy

초기 Operator 생성에서는 필드 타입과 JSON tag를 우선 정확히 만든다.
validation/defaulting은 요구사항에 명시된 경우에만 추가하는 것이 안전하다.

