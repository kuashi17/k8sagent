# Status Update Pattern Guide

metadata:
- source: internal-authored
- category: guide
- topic: status update

## Status Subresource

Kubebuilder CRD는 status subresource를 사용할 수 있다.
Controller가 status를 갱신하려면 RBAC marker에 `<plural>/status` 권한이 필요하다.

예시:

```go
// +kubebuilder:rbac:groups=app.beginner.sample.io,resources=appconfigs/status,verbs=get;update;patch
```

## Update Pattern

Reconcile에서는 spec을 읽어 하위 리소스를 생성/조회하고, 그 결과를 status에 반영한다.
status.phase, status.message, 하위 리소스 이름 같은 필드는 사용자가 아니라 Controller가 갱신한다.

## Common Failure

`forbidden: cannot update resource .../status` 오류는 status subresource RBAC이 빠졌을 때 발생한다.
이 경우 artifact patcher로 RBAC marker를 보정하고 `make manifests`를 다시 실행한다.

