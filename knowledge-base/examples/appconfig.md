# AppConfig Example

AppConfig는 초보 개발자에게 적합한 ConfigMap 기반 Operator 예시다.

요구사항 핵심:

- domain: `beginner.sample.io`
- group: `app`
- version: `v1alpha1`
- kind: `AppConfig`
- spec: `appName`, `configData`, `enabled`
- status: `phase`, `configMapName`, `message`
- 관리 리소스: `ConfigMap`

Controller 동작:

- AppConfig 변경을 감지한다.
- `spec.enabled=true`이면 ConfigMap을 생성한다.
- ConfigMap data에는 `spec.configData` 값을 반영한다.
- `spec.enabled=false`이면 ConfigMap을 생성하지 않고 status.phase를 `Disabled`로 갱신한다.
- ConfigMap 생성 여부를 확인해 status를 갱신한다.

이 예시는 GPU, PVC, StatefulSet 같은 복잡한 요소 없이 CRD, ConfigMap, status 갱신 개념을 설명하기 좋다.

