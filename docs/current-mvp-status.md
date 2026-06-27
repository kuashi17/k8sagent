# Current MVP Status

기준일: 2026-06-28

## 현재 동작하는 범위

- 자연어 요구사항 분석과 profile hint 선택
- Local LLM 기반 requirement planning, tool-result evaluation, recovery planning
- LLM JSON schema 검증, 누락 필드 정규화, schema 재요청 1회
- 계획 캐시, 짧은 planning prompt, Web 시작 시 선택적 model warm-up
- Tool allowlist, 필수 인자, repository path, execute 승인 검증
- `operator-spec.yaml`, command plan, Kubebuilder scaffold, artifact patch 생성
- 동작 중심 ManagedResourceSpec IR과 catalog/LLM capability 계약 검증
- catalog에 없는 리소스의 제안, Kubernetes discovery 확인, 별도 승인
- `make generate`, `make manifests`, `make test` 검증
- profile capability 기반 kind deployment
- 공통 kind 배포 엔진과 profile validator 분리
- AppConfig, TrainingJob, RedisCache 실제 kind lifecycle validator
- 공통 namespace/service-account RBAC preflight
- 재사용 kind 클러스터별 kubectl context 강제 전환
- profile별 artifact controller/RBAC hook과 멱등성 검증
- 실패 시 Tool 실행 중단, deterministic recovery 분류, 승인 대기 recovery plan
- Local Markdown 기반 Hybrid RAG와 keyword fallback
- requirement RAG Hit@3 품질 gate와 reranker latency 지표
- requirement/log-analysis evidence trace, safety evaluation, Markdown report
- Web UI 백그라운드 작업, 상태 polling, 로그 표시, 최근 작업 목록, 취소
- 외부 다중 worker queue, SSE 로그, 제한 재시도, 수동 rollback 정책
- Web 서버 재시작 시 미완료 작업의 `interrupted` 복구
- 초보자용 빈 입력, 작성 도움말, 한국어 진행 상태, 계획 후 실행 승인 UI
- HTTP 제출부터 외부 worker, 결과 표시까지 이어지는 사용자 여정 계약 테스트
- legacy Job e2e adapter의 Pydantic profile 계약과 profileless 실행 차단

## 주요 모듈 경계

| 모듈 | 책임 |
| --- | --- |
| `agent/langchain_agent.py` | CLI와 상위 orchestration |
| `agent/context_builder.py` | requirement/profile/RAG context 조립 |
| `agent/retrieval_context.py` | RAG 결과 정규화와 context 선별 |
| `agent/tool_validator.py` | LLM schema와 Tool 호출 검증 |
| `agent/execution_engine.py` | Tool capability, 정렬, 실행, timing |
| `agent/recovery_policy.py` | 오류 분류와 recovery 승인 정책 |
| `agent/recovery_orchestrator.py` | deterministic/LLM recovery 흐름 선택 |
| `agent/final_evaluator.py` | 축약 final LLM 평가와 fallback 진입 |
| `agent/llm_cache.py` | planning cache key, read/write |
| `agent/failure_context.py` | 실패 evidence와 누락 산출물 context 조립 |
| `agent/summary_builder.py` | 최종 summary 계약 조립 |
| `agent/evidence_builder.py` | safety/evidence 조립 |
| `agent/report_writer.py` | JSON/Markdown 보조 산출물 기록 |
| `agent/report_renderer.py` | 사용자용 보고서 렌더링 |
| `agent/tools/kind_deployment_runner.py` | 공통 kind 배포 lifecycle |
| `agent/tools/kind_deployment_validators.py` | profile별 리소스/status 검증 |
| `web/job_manager.py` | 영속 queue, claim, 취소, 재시도 정책 |
| `web/worker.py` | 다중 프로세스 외부 작업 실행 |

## 검증 상태

공통 진입점:

```bash
python3 scripts/run-regression-tests.py --suite quick
python3 scripts/run-regression-tests.py --suite standard
python3 scripts/run-regression-tests.py --suite full
```

2026-06-28 현재 확인 결과:

- Agent 45개, LLM 3개, Tool 86개, Evaluation 26개 단위 테스트 통과
- Web 단위·통합 테스트 24개 통과
- `quick` regression 통과
- requirement RAG fixture Hit@3 1.0 통과
- Local LLM Agent 1회를 포함한 `standard` regression 통과
- Docker/kind 기반 `full` regression 통과
- AppConfig create/update/disabled/delete/restore lifecycle 통과
- TrainingJob Job create/delete/restore lifecycle 통과
- RedisCache StatefulSet/Service create/delete/restore lifecycle 통과
- 실제 Agent standard execute → validation → kind deployment 경로 통과
- profileless Controller 13종 컴파일·품질 평가 통과
- profileless kind 9종, lifecycle check 39개 통과
- 최신 full regression 425.389초, 최종 평가 100점

```bash
python3 scripts/run-regression-tests.py --suite full
```

최근 성공 CI:

- full: GitHub Actions run `28290730432`
- beginner Web UI quick regression: GitHub Actions run `28304854406`

## 안전 정책

- 기본 모드는 `dry-run`이다.
- 변경 Tool은 `--execute`와 사용자 승인이 모두 있어야 실제 실행된다.
- invalid JSON 또는 schema 검증 실패가 복구되지 않으면 Tool을 실행하지 않는다.
- Tool 실패 후 다음 Tool은 실행하지 않는다.
- Tool이 모두 성공한 뒤 final LLM 평가만 timeout되면 deterministic summary로 강등하고 warning을 남긴다.
- recovery Tool은 `requiresApproval=true`로 저장되며 자동 실행하지 않는다.
- Docker/kind 연결 실패는 `docker-kind-connection`으로 분류하고 불필요한 recovery LLM 호출을 생략한다.

## 현재 한계와 다음 개선

1. 역할별 모델 성능을 실제 장비에서 측정해 planning/final 기본 모델 조합을 조정해야 한다.
2. `langchain_agent.py`에는 requirement/log-analysis 상위 orchestration이 남아 있어 추가 분리가 가능하다.
3. Web의 외부 worker queue는 로컬 파일 기반이므로 여러 호스트에서 운영하려면 공유 POSIX volume 또는 외부 queue backend가 필요하다.
4. 취소는 Agent subprocess를 종료하지만 이미 외부 시스템에 반영된 변경을 자동 rollback하지 않는다.
5. kind validator는 profile별 구현을 추가해야 새로운 Operator lifecycle을 깊게 검증할 수 있다.
6. RAG 품질은 fixture 확대와 reranker 성능 측정이 더 필요하다.
7. Jenkins, Harbor, Argo CD 연계는 아직 문서/확장 단계다.

## 내부 fixture의 위치

AppConfig/ConfigMap과 TrainingJob은 회귀 검증용 fixture다. Agent core는 특정 Operator에 종속되지 않으며 자연어 requirement를 우선하고 profile은 capability와 검증 hint로만 사용한다.
