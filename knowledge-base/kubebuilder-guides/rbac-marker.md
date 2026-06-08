# RBAC Marker Guide

Kubebuilder Controller가 Kubernetes 리소스를 조회하거나 생성하려면 RBAC 권한이 필요하다. 권한은 보통 Controller 파일의 marker로 선언하고 `make manifests`로 RBAC YAML을 생성한다.

예시:

```go
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=configmaps,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=sample.io,resources=appconfigs/status,verbs=get;update;patch
```

요구사항 작성 시에는 Controller가 직접 생성하는 리소스와 조회만 하는 리소스를 구분하면 좋다.

- 직접 생성/수정/삭제: `get,list,watch,create,update,patch,delete`
- 상태 조회만 수행: `get,list,watch`
- Custom Resource status 갱신: `<plural>/status`에 `get,update,patch`

RBAC 오류가 발생하면 `forbidden`, `cannot get resource`, `cannot create resource` 같은 로그가 나타날 수 있다.

