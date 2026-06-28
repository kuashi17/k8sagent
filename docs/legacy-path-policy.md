# Legacy Path Policy

Legacy 경로는 이름만 바꿔 숨기지 않고 `config/legacy-path-policy.yaml`에 등록합니다.
Quick CI는 실제 참조 위치와 개수를 `legacy-usage.json`에 기록하며, 허용 목록 밖에
새 참조가 생기면 실패합니다.

현재 유지되는 경로는 profile 기반 `job-workload-v1` 검증 adapter 하나입니다.
이는 profileless 생성 경로에서는 호출할 수 없고 명시적인 Pydantic 계약이 있어야
실행됩니다. 남은 profile이 공통 `managed-resources` validator 계약으로 이관되면
adapter와 관련 계약·테스트를 함께 제거합니다.

Validator 식별자는 계약 모듈의 단일 상수로 통합하고 구형 타입 이름을 제거해 추적
참조를 19개에서 4개로 줄였습니다. 10개와 5개 감소 milestone을 통과했으며 CI
상한도 4로 낮췄습니다. 남은 참조는 Pydantic Literal, 단일 상수, 실제 profile과
adapter import 경계이며 공통 validator 이관 시 함께 0으로 제거합니다.

기존 `/runs/{type}/{id}` Web redirect는 현재 `/runs/job/{id}`와 API가 모든 사용처를
대체하므로 제거했습니다. 새 호환 경로가 필요하면 먼저 정책에 종료 조건과 허용
파일을 등록해야 합니다.
