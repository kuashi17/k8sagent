# Finalizer Pattern Guide

metadata:
- source: internal-authored
- category: guide
- topic: finalizer cleanup

## When to Use Finalizers

Finalizer는 Custom Resource 삭제 전에 외부 리소스 정리 작업이 필요한 경우 사용한다.
Kubernetes 내부 하위 리소스만 ownerReference로 관리한다면 finalizer가 항상 필요한 것은 아니다.

## Typical Flow

1. 리소스 생성 시 finalizer가 없으면 추가한다.
2. deletionTimestamp가 설정되면 외부 리소스를 정리한다.
3. 정리가 끝나면 finalizer를 제거한다.
4. Kubernetes가 Custom Resource 삭제를 완료한다.

## Caution

finalizer를 추가하면 RBAC에 `<resources>/finalizers` 권한이 필요할 수 있다.
MVP에서 finalizer를 사용하지 않는다면 불필요한 권한을 추가하지 않는 것이 좋다.

## Recovery

삭제가 멈추면 finalizer 정리 로직 실패, 외부 API 오류, RBAC 부족을 확인한다.
Agent는 finalizer 사용 여부가 명확하지 않으면 manual review로 분류해야 한다.

