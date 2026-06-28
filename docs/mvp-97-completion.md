# MVP 97% Completion and Feature Freeze

이 문서는 초보 Controller 개발자를 위한 제품형 MVP의 기능 개선 종료 기준입니다.

## 완료 기준

- 자연어 요구사항부터 spec, IR, 생성 코드, make, kind 검증까지 단방향 실행
- LLM 계약 오류와 승인되지 않은 Tool/capability 실행 차단
- capability별 stable/beta/experimental 자동 산출
- 등급별 evidence run, `lastValidatedAt`, 판정 기준, 제한사항 공개
- Web 계획→승인→생성 여정의 automation/approval/total 시간 분리
- 감시 대상, RBAC 이유, 삭제 정책, 먼저 볼 파일을 `AgentResult`로 제공
- 멱등성, drift, RBAC 최소 권한, 삭제, finalizer, 상태 머신 runtime evidence
- Full 핵심 job 600초와 통합 관찰 1,200초 gate
- legacy 참조 19개에서 4개로 감소하고 재증가 차단

## Feature Freeze

이 시점부터 새로운 생성 기능과 대규모 구조 변경은 MVP 범위에 추가하지 않습니다.
허용되는 변경은 버그·보안 취약점·호환성 문제·성능 회귀 수정, 테스트 안정화,
실제 evidence에 따른 capability 등급 승격과 legacy 최종 제거입니다.

남은 3%는 신규 기능이 아니라 실제 사용자 여정 데이터 축적, beta/experimental의
근거 기반 승격, 마지막 profile adapter 제거입니다.
