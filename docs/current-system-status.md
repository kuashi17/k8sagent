# Current System Status

기준일: 2026-07-10

이 문서는 현재 저장소 기준으로 동작하는 범위와 검증 상태를 요약합니다.
향후 계획이 아니라, 지금 코드와 테스트로 확인 가능한 기능만 기록합니다.

## 현재 동작 범위

- 자연어 Operator 요구사항 분석
- API group/version/kind, spec/status, 관리 리소스, 삭제 정책 추출
- 필수 정보 누락과 모순 요구사항에 대한 clarification-required 처리
- Local Markdown 기반 RAG 검색
- Ollama 호환 Local LLM planning
- Pydantic 기반 RequirementPlan, ToolCall, ToolResult, AgentResult 계약 검증
- Tool allowlist, repository path guard, execute approval gate
- `operator-spec.yaml`과 command plan 생성
- Kubebuilder scaffold 생성
- CRD 타입, sample YAML, RBAC marker, Controller 코드 보정
- `make generate`, `make manifests`, `make test` 검증
- Deployment, Job, ConfigMap, PVC, read-only Deployment 등 profileless lifecycle 검증
- Docker/kind 기반 create/update/drift/delete/read-only/retain evidence 수집
- Docker daemon unavailable, kind 연결 실패 등 인프라 오류 분리
- Web UI의 계획 확인, 승인, 코드 생성, kind 검증, 결과 설명
- 실패 로그 분석과 recovery plan 제안

## 주요 품질 장치

- LLM JSON 출력은 schema 검증을 통과해야 한다.
- schema repair가 실패하면 Tool을 실행하지 않는다.
- Tool 실패 후 후속 Tool은 실행하지 않는다.
- 복구 계획은 자동 실행하지 않고 사용자 확인 대상으로 남긴다.
- `not-run` lifecycle 항목은 capability 승격 근거로 사용하지 않는다.
- capability 등급은 Custom Resource 이름이 아니라 관리 리소스와 lifecycle 패턴의 evidence로 계산한다.
- generated/logs/workspace/evaluation results는 실행 산출물이며 기본적으로 git에 누적하지 않는다.

## 검증 방법

```bash
python3 scripts/run-regression-tests.py --suite quick
python3 scripts/run-regression-tests.py --suite standard
python3 scripts/run-regression-tests.py --suite full
```

검증 범위:

- 단위 테스트
- Web 사용자 여정 테스트
- RAG 품질 gate
- response consistency
- reliability negative tests
- profileless compile matrix
- profileless kind lifecycle matrix

## 현재 제한사항

- 100% 범용 자연어 이해 시스템은 아니다. 필수 API 정보나 필드 타입이 모호하면 추가 정보를 요청한다.
- Local LLM 품질과 응답 속도는 실행 장비와 모델 설정에 영향을 받는다.
- Docker/kind 검증은 Docker Desktop, WSL integration, kubectl context 상태에 의존한다.
- experimental capability는 생성 가능하더라도 실제 kind lifecycle evidence가 부족하므로 코드와 RBAC 검토가 필요하다.
- 외부 CI/CD, image registry, GitOps 시스템 연계는 현재 핵심 실행 경로가 아니다.
