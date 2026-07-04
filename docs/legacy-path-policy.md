# Legacy Path Policy

Legacy 경로는 이름만 바꿔 숨기지 않고 `config/legacy-path-policy.yaml`에 등록합니다.
Quick CI는 실제 참조 위치와 개수를 `legacy-usage.json`에 기록하며, 허용 목록 밖에
새 참조가 생기면 실패합니다.

profile 기반 Job 전용 검증 adapter는 공통 `managed-resources` validator로 이관해
제거했습니다. 추적 참조는 19개에서 0개가 되었고 정책의 `paths` 목록도 비었습니다.
Quick CI gate는 이후 구형 경로가 다시 추가되지 않는지 계속 확인합니다.

기존 `/runs/{type}/{id}` Web redirect는 현재 `/runs/job/{id}`와 API가 모든 사용처를
대체하므로 제거했습니다. 새 호환 경로가 필요하면 먼저 정책에 종료 조건과 허용
파일을 등록해야 합니다.
