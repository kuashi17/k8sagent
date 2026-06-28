# Quality and Time Thresholds

## Full CI 시간 기준

두 시간 기준은 측정 대상과 실패 의미가 다릅니다.

| 기준 | 범위 | 의미 |
| --- | --- | --- |
| 600초 | `full` 핵심 job의 시작부터 종료까지 | 코드 생성, 컴파일, Docker, kind 검증의 성능 회귀 gate |
| 1,200초 | runner queue와 `full` job을 합한 사용자 관찰 시간 | runner 부족이나 환경 지연까지 포함한 통합 운영 기준 |

600초를 넘으면 구현 또는 Docker/kind 단계의 성능 회귀로 봅니다. 핵심 job은
600초 이내지만 1,200초를 넘으면 runner 가용성 또는 queue 운영 문제로 분류합니다.
Timing report와 artifact 업로드는 측정 결과를 만드는 단계이므로 두 예산에 포함하지
않습니다.

## Web 사용자 여정

각 Web job은 `journeyTimings`에 다음 값을 기록합니다.

- `queueSeconds`: 제출부터 worker 시작까지
- `executionSeconds`: worker 실행 시간
- `totalJourneySeconds`: 제출부터 최종 결과까지
- `agentSeconds`: Agent 내부에서 측정한 전체 실행 시간

Web 성능 목표는 cold/warm, dry-run/execute, kind 사용 여부를 구분해 이후 실제 사용
데이터로 설정합니다. CI 시간과 Web 사용자 시간은 서로 대체하지 않습니다.

## Capability 등급

- `stable`: compile, kind, 멱등성, drift 복구, RBAC 최소 권한, 삭제, 상태 머신 통과
- `beta`: kind 기본 lifecycle은 통과했지만 일부 runtime 증거가 제한됨
- `experimental`: catalog/schema 또는 compile 증거만 존재

Full CI는 `capability-matrix.json`을 자동 생성합니다. UI의 기본 등급은 마지막으로
검토된 Full 실행을 `config/capability-support.yaml`에 승격한 값입니다.

## Legacy 감소

Legacy 참조는 현재 기준선보다 증가할 수 없습니다. 공통 validator 이관으로 참조가
줄어들 때마다 `maxReferences`를 새 개수로 낮추며 최종 목표는 0입니다.
