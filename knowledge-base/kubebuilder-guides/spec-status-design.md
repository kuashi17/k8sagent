# Spec and Status Design Guide

metadata:
- source: internal-authored
- category: guide
- topic: spec status design

## Spec

`spec`은 사용자가 원하는 상태다. 예를 들어 AppConfig의 `spec.configData`는
ConfigMap에 들어갈 설정 값을 의미하고, TrainingJob의 `spec.image`는 Job container image를 의미한다.
Agent는 spec 필드를 Go struct field와 JSON tag로 변환한다.

## Status

`status`는 Controller가 관찰한 실제 상태다. status에는 phase, ready count,
생성된 하위 리소스 이름, message 같은 값을 둔다. 사용자가 직접 입력하는 값이 아니라
Controller가 Reconcile 중 갱신한다.

## Supported Field Types

MVP에서 안정적으로 지원하는 타입은 다음과 같다.

- `string`
- `bool`
- `int`, `int32`, `int64`
- `float32`, `float64`
- `[]string`
- `map[string]string`
- `metav1.Time`

`notatype`처럼 Go 타입으로 해석할 수 없는 값은 invalid-field-type 오류로 분류한다.

## Recovery Signal

`make generate`에서 `invalid field type` 메시지가 나오면 controller-gen 재실행만으로 해결되지 않는다.
요구사항 또는 operator spec의 필드 타입을 먼저 수정한 뒤 spec 생성, artifact patch, validation을 다시 수행해야 한다.

