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

## Hybrid RAG 검색 구조

`agent/rag/retriever.py`는 `knowledge-base` 아래 Markdown 문서를 검색한다. 초기 MVP의 keyword 검색은 fallback 및 비교용으로 유지하고, 기본 검색 흐름은 FAISS Vector DB 기반 Hybrid RAG로 확장한다.

현재 검색 대상:

- Kubebuilder 기본 흐름
- RBAC marker
- Reconcile 패턴
- 공통 오류 해결
- AppConfig 예시
- TrainingJob 예시

현재 기본 흐름:

```text
knowledge-base Markdown
  -> document_loader chunk 분할
  -> Ollama embedding
  -> FAISS index
  -> vector search
  -> keyword search
  -> hybrid score 결합
  -> optional Local LLM reranker
  -> Top 3 context
  -> LLM Planner 입력
```

관련 파일:

- `agent/rag/document_loader.py`: Markdown 문서 로딩 및 chunk 분할
- `agent/rag/embedding_client.py`: Ollama local embedding 호출
- `agent/rag/vector_store.py`: FAISS index 저장/로드/검색
- `agent/rag/hybrid_retriever.py`: vector + keyword 검색 결과 결합
- `agent/rag/reranker.py`: Local LLM 기반 context reranking
- `agent/rag/build_index.py`: index build CLI
- `agent/rag/retriever.py`: keyword/vector/hybrid/hybrid-rerank 통합 API

RAG 관련 환경변수:

- `RAG_MODE`, 기본값 `hybrid`
- `RAG_TOP_K`, 기본값 `8`
- `RAG_FINAL_TOP_N`, 기본값 `3`
- `RAG_RERANK_ENABLED`, 기본값 `false`
- `RAG_KEYWORD_FALLBACK`, 기본값 `true`
- `OLLAMA_BASE_URL`, 기본값 `http://127.0.0.1:11434`
- `LOCAL_EMBEDDING_MODEL`, 기본값 `nomic-embed-text`

Vector index가 없거나 embedding model이 준비되지 않은 개발 환경에서는 keyword fallback을 사용할 수 있다. fallback 발생 여부는 Agent log의 `retrievalDetails.fallbackUsed`와 `selected-context.json`에서 확인한다.

CPU 노트북 기본값은 Hybrid 검색이며 reranker는 꺼져 있다. reranker 검증이 필요할 때만 다음처럼 별도 실행한다.

```bash
export RAG_MODE=hybrid-rerank
export RAG_RERANK_ENABLED=true
export LOCAL_LLM_TIMEOUT_SECONDS=120
```

검색 품질은 `evaluation/rag-evaluation-dataset.yaml`과 `agent/evaluation/rag_evaluator.py`로 정량 평가한다. 평가기는 `keyword`, `vector`, `hybrid`, `hybrid-rerank`를 비교하고 Hit@1, Hit@3, Recall@3, Recall@5, MRR, 평균 latency, P95 latency, fallback count, reranker timeout count를 저장한다.

Agent report에는 검색 결과만 나열하지 않고, LLM이 각 문서를 어떤 판단에 사용했는지도 별도 섹션으로 기록한다.

```text
RAG Evidence Used By LLM
- knowledge-base/kubebuilder-guides/basic-flow.md
  - used for: Kubebuilder scaffold, generate, manifests, test 단계 계획
- knowledge-base/kubebuilder-guides/rbac-marker.md
  - used for: 관리 대상 리소스에 필요한 RBAC marker 판단
- knowledge-base/kubebuilder-guides/reconcile-pattern.md
  - used for: Controller Reconcile 책임과 status 갱신 방식 판단
```

## LLM Planner

본 시스템은 LLM planner 기반 Agent 구조를 사용한다. LLM planner는 실제 Chat Model 호출을 수행하고, RAG 검색 결과를 입력으로 받아 요구사항 요약, 부족 정보 판단, profile 추천, Tool 호출 계획, 위험 요소, 다음 조치를 JSON으로 생성한다.

현재 지원 provider:

- `local`: Ollama OpenAI-compatible endpoint 사용

환경변수:

- `LOCAL_LLM_BASE_URL`, 기본값 `http://localhost:11434/v1`
- `LOCAL_LLM_MODEL`, 기본값 `qwen2.5-coder:3b`

본 시스템은 외부 API 기반 LLM을 사용하지 않는다. 사내 예제 코드, Kubernetes 로그, YAML 산출물, 오류 로그, RAG 문서는 로컬 환경 안에서 처리된다. 이 구조는 내부망/폐쇄망 환경을 고려한 로컬 실행형 AI Agent 구조다.

모델은 직접 `kubectl`, `make`, `python` 명령을 실행하지 않는다. 모델은 요구사항 해석, RAG 근거 연결, Tool 호출 계획, 로그 분석 판단을 JSON으로 생성하는 판단 엔진 역할만 수행한다. 실제 실행은 `agent/tools/langchain_wrappers.py`의 허용된 Tool wrapper가 담당한다.

LLM planner 역할:

- 요구사항 요약
- 부족한 정보 식별
- RAG 검색 결과 요약 및 판단 근거 연결
- profile 추천
- Tool 호출 계획과 호출 이유 생성
- 위험 요소와 다음 조치 제안
- 로그 분석 시 성공/실패/warning 판단과 beginner-friendly 설명 생성

LLM은 명령을 직접 실행하지 않는다. 실제 실행은 기존 Tool wrapper가 담당하며, `--execute`가 명시되지 않으면 scaffold, patch, e2e는 dry-run 중심으로 제한된다.

LLM 호출에 실패하거나 Ollama 서버/모델이 준비되지 않으면 Agent는 다른 provider로 대체하지 않는다. 대신 실패 원인과 필요한 환경변수를 출력하고, `logs/agent/<timestamp>/summary.json`, `agent-report.md`, `llm-output.json`, `llm-raw-output.txt`에 기록한다.

LLM 입출력 파일:

- `llm-input.json`
- `llm-output.json`
- `llm-raw-output.txt`
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
