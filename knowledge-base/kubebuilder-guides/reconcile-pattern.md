# Reconcile Pattern

Controller의 Reconcile 함수는 Custom Resource의 현재 상태와 사용자가 원하는 상태를 비교한 뒤 Kubernetes 리소스를 생성하거나 갱신한다.

기본 패턴:

1. Custom Resource를 `Get` 한다.
2. 삭제된 리소스라면 조용히 종료한다.
3. spec 값을 읽어 관리 대상 리소스 이름과 원하는 spec을 만든다.
4. 하위 리소스가 없으면 생성한다.
5. 이미 있으면 필요한 경우 갱신한다.
6. 하위 리소스 상태를 조회한다.
7. Custom Resource status를 갱신한다.

하위 리소스가 Kubernetes 내부 리소스라면 보통 ownerReference를 설정해 Custom Resource 삭제 시 함께 정리되도록 한다.

초보자용 예시인 AppConfig는 ConfigMap을 생성하고, `spec.enabled=false`이면 ConfigMap을 만들지 않고 status를 `Disabled`로 갱신하는 단순 Reconcile 패턴을 따른다.

