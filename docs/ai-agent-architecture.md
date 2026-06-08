# AI Agent Architecture

## 목적

이 프로젝트는 단순 Python 자동화 스크립트 모음이 아니라, Kubebuilder 기반 Operator 개발 절차를 이해하고 단계별 도구를 선택해 실행하는 AI Agent 구조를 지향한다.

기존 CLI 도구는 그대로 유지하고, 그 위에 LangChain 기반 Orchestrator 계층과 RAG 검색 계층을 추가한다.

## 계층 구조

```text
User requirement
  -> LangChain-style Agent Orchestrator
  -> Local RAG Retriever
  -> Tool wrappers
  -> Existing CLI tools
  -> Generated specs, command plans, scaffold, patches, e2e logs
```

## 기존 자동화 파이프라인과 Agent 계층

기존 파이프라인은 다음 도구로 구성되어 있다.

- `spec_generator.py`: 자연어 요구사항을 `operator-spec.yaml`로 변환
- `command_planner.py`: 스펙을 Kubebuilder 실행 계획으로 변환
- `scaffold_runner.py`: scaffold dry-run, preflight, execute 수행
- `artifact_patcher.py`: API 타입, sample YAML, RBAC marker 보정
- `e2e_runner.py`: kind 기반 e2e 검증
- `log_analyzer.py`: 실행 로그와 summary 분석

Agent 계층은 이 도구를 직접 대체하지 않는다. 대신 각 도구를 Tool로 감싸고, 요구사항과 검색 문서를 바탕으로 어떤 도구를 어떤 순서로 호출할지 결정한다.

## Tool Wrapping 구조

`agent/tools/langchain_wrappers.py`는 기존 Python CLI를 subprocess로 호출한다.

각 Tool wrapper는 다음 값을 반환한다.

- command
- stdout
- stderr
- exitCode
- status

실패해도 예외로 즉시 종료하지 않고 결과 객체를 반환하므로, Agent가 실패 단계와 다음 조치를 자연어로 설명할 수 있다.

## RAG 검색 구조

`agent/rag/retriever.py`는 `knowledge-base` 아래 Markdown 문서를 읽어 키워드 기반 검색을 수행한다.

현재 검색 대상:

- Kubebuilder 기본 흐름
- RBAC marker
- Reconcile 패턴
- 공통 오류 해결
- AppConfig 예시
- TrainingJob 예시

현재는 Vector DB를 사용하지 않지만, 검색 결과는 문서 경로, 제목, 매칭 키워드, 발췌문 형식으로 고정되어 있다. 이후 embedding, Vector DB, reranker로 교체할 수 있다.

## mock-planner와 LLM planner

현재 기본 planner는 `mock`이다.

mock-planner는 규칙 기반으로 다음을 수행한다.

- requirement에서 kind, domain, group, version, 관리 리소스를 추정
- RAG 검색 수행
- 실행 단계 생성
- 기존 Tool wrapper 호출
- 결과를 Markdown report로 요약

`llm` planner는 실제 Chat Model 호출을 수행하는 planner다.

현재 지원 provider:

- `openai`: `langchain-openai`의 `ChatOpenAI` wrapper 사용
- `local`: Ollama 호환 HTTP API 사용
- `disabled`: LLM 호출 비활성화

환경변수:

- `OPENAI_API_KEY`
- `OPENAI_MODEL`, 기본값 `gpt-4.1-mini`
- `LOCAL_LLM_BASE_URL`, 기본값 `http://localhost:11434`
- `LOCAL_LLM_MODEL`, 기본값 `llama3.1`

LLM planner 역할:

- 요구사항 요약
- 부족한 정보 식별
- RAG 검색 결과 요약
- profile 추천
- Tool 호출 계획 생성
- 로그 분석 시 성공/실패/warning 판단과 beginner-friendly 설명 생성

LLM은 명령을 직접 실행하지 않는다. 실제 실행은 기존 Tool wrapper가 담당하며, `--execute`가 명시되지 않으면 scaffold, patch, e2e는 dry-run 중심으로 제한된다.

LLM 호출에 실패하거나 API key가 없으면 Agent는 `mock` planner로 fallback한다. fallback 여부와 원인은 `logs/agent/<timestamp>/summary.json`, `agent-report.md`, `llm-output.json`에 기록된다.

로컬 open model 예:

```bash
ollama serve
ollama pull llama3.1
export LLM_PROVIDER=local
export LOCAL_LLM_MODEL=llama3.1
python3 agent/langchain_agent.py \
  --requirement requirements/appconfig.txt \
  --profile profiles/appconfig.yaml \
  --planner local \
  --mode dry-run
```

LLM 입출력 파일:

- `llm-input.json`
- `llm-output.json`
- `retrieved-docs.json`
- `tool-results.json`

## 왜 AI Agent 구조인가

단순 자동화 스크립트는 정해진 명령을 순서대로 실행한다.

이 프로젝트의 Agent 구조는 다음 점에서 다르다.

- 자연어 요구사항을 요약하고 누락 정보를 점검한다.
- 관련 Kubebuilder 지식 문서를 검색해 실행 근거로 사용한다.
- profile과 요구사항을 함께 보고 단계별 Tool을 선택한다.
- Tool 실행 결과를 수집하고 다음 행동을 제안한다.
- 실제 LLM planner가 RAG 문서와 실행 로그를 함께 읽고 JSON 계획 또는 분석 결과를 생성할 수 있다.

즉, CLI 도구는 실행 능력을 제공하고 Agent는 판단, 검색, 설명, 단계 선택을 담당한다.

## 안전장치

- 기본 실행은 dry-run이다.
- `--execute`가 명시되지 않으면 scaffold, patch, e2e 같은 변경 작업은 실제 실행하지 않는다.
- Agent는 실행 전 호출할 명령을 출력한다.
- 실행 결과는 `logs/agent/<timestamp>/summary.json`과 `agent-report.md`에 저장한다.

## 향후 연계 위치

- GitHub: 생성 결과 branch, commit, PR 초안 생성
- Jenkins: `make generate`, `make manifests`, `make test`, image build 검증 로그 수집
- Harbor: Operator image build/push 결과 확인
- Argo CD: 배포 반영, sync 상태, health 상태 수집

이 외부 시스템 연계도 Tool wrapper로 추가하고, Agent planner가 필요한 시점에 호출하는 구조로 확장한다.
