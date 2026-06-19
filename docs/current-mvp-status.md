# Current MVP Status

기준일: 2026-06-19

## 현재 동작하는 범위

- 자연어 요구사항 분석과 profile hint 선택
- Local LLM 기반 requirement planning, tool-result evaluation, recovery planning
- LLM JSON schema 검증, 누락 필드 정규화, schema 재요청 1회
- 계획 캐시, 짧은 planning prompt, Web 시작 시 선택적 model warm-up
- Tool allowlist, 필수 인자, repository path, execute 승인 검증
- `operator-spec.yaml`, command plan, Kubebuilder scaffold, artifact patch 생성
- `make generate`, `make manifests`, `make test` 검증
- profile capability 기반 kind deployment
- 공통 kind 배포 엔진과 profile validator 분리
- 실패 시 Tool 실행 중단, deterministic recovery 분류, 승인 대기 recovery plan
- Local Markdown 기반 Hybrid RAG와 keyword fallback
- requirement/log-analysis evidence trace, safety evaluation, Markdown report
- Web UI 백그라운드 작업, 상태 polling, 로그 표시, 최근 작업 목록, 취소
- Web 서버 재시작 시 미완료 작업의 `interrupted` 복구

## 주요 모듈 경계

| 모듈 | 책임 |
| --- | --- |
| `agent/langchain_agent.py` | CLI와 상위 orchestration |
| `agent/context_builder.py` | requirement/profile/RAG context 조립 |
| `agent/tool_validator.py` | LLM schema와 Tool 호출 검증 |
| `agent/execution_engine.py` | Tool capability, 정렬, 실행, timing |
| `agent/recovery_policy.py` | 오류 분류와 recovery 승인 정책 |
| `agent/failure_context.py` | 실패 evidence와 누락 산출물 context 조립 |
| `agent/summary_builder.py` | 최종 summary 계약 조립 |
| `agent/evidence_builder.py` | safety/evidence 조립 |
| `agent/report_writer.py` | JSON/Markdown 보조 산출물 기록 |
| `agent/report_renderer.py` | 사용자용 보고서 렌더링 |
| `agent/tools/kind_deployment_runner.py` | 공통 kind 배포 lifecycle |
| `agent/tools/kind_deployment_validators.py` | profile별 리소스/status 검증 |
| `web/job_manager.py` | 영속 백그라운드 작업과 취소/재시작 복구 |

## 검증 상태

공통 진입점:

```bash
python3 scripts/run-regression-tests.py --suite quick
python3 scripts/run-regression-tests.py --suite standard
python3 scripts/run-regression-tests.py --suite full
```

2026-06-19 현재 확인 결과:

- Agent 단위 테스트 20개 통과
- Web 단위 테스트 7개 통과
- `quick` regression 통과
- Local LLM Agent 1회를 포함한 `standard` regression 통과
- Docker daemon이 꺼져 있어 `full`의 kind 실배포 검증은 미실행

Docker가 복구되면 다음 명령으로 공통 배포 엔진, AppConfig/ConfigMap validator, profileless 요구사항을 함께 재검증한다.

```bash
python3 scripts/run-regression-tests.py --suite full
```

## 안전 정책

- 기본 모드는 `dry-run`이다.
- 변경 Tool은 `--execute`와 사용자 승인이 모두 있어야 실제 실행된다.
- invalid JSON 또는 schema 검증 실패가 복구되지 않으면 Tool을 실행하지 않는다.
- Tool 실패 후 다음 Tool은 실행하지 않는다.
- recovery Tool은 `requiresApproval=true`로 저장되며 자동 실행하지 않는다.
- Docker/kind 연결 실패는 `docker-kind-connection`으로 분류하고 불필요한 recovery LLM 호출을 생략한다.

## 현재 한계와 다음 개선

1. Docker 복구 후 `full` regression과 kind standard workflow를 실제로 완료해야 한다.
2. `langchain_agent.py`에는 final/recovery orchestration, retrieval 선택, failure context 조립이 남아 있어 추가 분리가 가능하다.
3. Web job은 단일 프로세스의 메모리 process registry를 사용한다. 다중 worker 운영에는 외부 queue/worker가 필요하다.
4. 취소는 Agent subprocess를 종료하지만 이미 외부 시스템에 반영된 변경을 자동 rollback하지 않는다.
5. kind validator는 profile별 구현을 추가해야 새로운 Operator lifecycle을 깊게 검증할 수 있다.
6. RAG 품질은 fixture 확대와 reranker 성능 측정이 더 필요하다.
7. Jenkins, Harbor, Argo CD 연계는 아직 문서/확장 단계다.

## 내부 fixture의 위치

AppConfig/ConfigMap과 TrainingJob은 회귀 검증용 fixture다. Agent core는 특정 Operator에 종속되지 않으며 자연어 requirement를 우선하고 profile은 capability와 검증 hint로만 사용한다.
