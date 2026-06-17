# Agent Evidence And Safety

## 목적

이 문서는 Local LLM Agent가 어떤 근거로 판단했고, Tool 실행이 어떤 안전장치를 거쳐 수행됐는지 확인하는 방법을 설명한다.

이 프로젝트는 GPU가 없는 CPU 환경에서도 시연 가능해야 하므로, 모델 크기보다 다음 항목을 명확히 남기는 것을 우선한다.

- RAG가 어떤 문서를 검색했는가
- LLM이 그 문서를 어떤 판단에 사용했는가
- LLM이 어떤 Tool 호출을 계획했는가
- Agent가 어떤 Tool 호출을 허용, 거부, 지연했는가
- 실제 Tool 실행 결과가 무엇인가
- 실패 시 복구 Tool이 자동 실행되지 않았는가

## 실행 흐름

```text
Requirement or log
  -> RAG retrieval
  -> Local LLM planning or analysis
  -> Tool call allowlist validation
  -> Safe Tool execution
  -> Tool result collection
  -> Final LLM evaluation or recovery planning
  -> evidenceTrace + safetyEvaluation 저장
```

## 핵심 로그 파일

Agent 실행 후 `logs/agent/<timestamp>/` 아래에서 다음 파일을 확인한다.

| 파일 | 의미 |
|---|---|
| `llm-input.json` | LLM에 실제로 전달된 requirement, RAG 문서, profile, 안전 모드 |
| `llm-output.json` | LLM이 생성한 요구사항 요약, 근거, Tool 호출 계획 |
| `llm-raw-output.txt` | 로컬 모델의 원문 응답 |
| `retrieved-docs.json` | 최종 선택된 RAG 문서 |
| `selected-context.json` | Agent가 LLM 입력으로 넘긴 문서와 선택 이유 |
| `validated-tool-calls.json` | allowlist, 인자, 경로 검증을 통과한 Tool 호출 |
| `rejected-tool-calls.json` | 거부된 Tool 호출과 이유 |
| `deferred-tool-calls.json` | dry-run 또는 사전 조건 때문에 지연된 Tool 호출 |
| `tool-results.json` | 실제 Tool 실행 결과와 exitCode |
| `final-llm-input.json` | Tool 실행 결과를 다시 LLM에 전달한 입력 |
| `final-llm-output.json` | 최종 실행 판단 |
| `evidence-trace.json` | RAG, LLM, Tool validation, 실행 결과를 연결한 근거 추적 |
| `safety-evaluation.json` | LLM provider, allowlist, dry-run gate, path gate 등 안전성 검증 결과 |
| `agent-report.md` | 사람이 읽는 최종 리포트 |

## Evidence Trace

`evidence-trace.json`은 다음 질문에 답하기 위한 파일이다.

- 요구사항에서 어떤 정보를 파싱했는가
- 어떤 RAG 문서가 선택됐고 왜 선택됐는가
- LLM이 어떤 근거로 Tool 계획을 만들었는가
- 어떤 Tool 호출이 검증을 통과했는가
- 실제 실행 exitCode는 무엇인가
- 최종 LLM 판단의 증거는 무엇인가
- 실패 시 recovery policy가 어떤 복구 계획을 검증했는가

예시 구조:

```json
{
  "ragEvidence": {
    "retrievalMode": "hybrid",
    "selectedDocuments": []
  },
  "toolValidationEvidence": {
    "validatedToolCalls": [],
    "rejectedToolCalls": [],
    "deferredToolCalls": []
  },
  "executionEvidence": [],
  "finalJudgmentEvidence": {}
}
```

## Safety Evaluation

`safety-evaluation.json`은 다음 안전 규칙을 기록한다.

| 안전 규칙 | 설명 |
|---|---|
| `llmProviderPolicy` | Ollama local LLM만 사용했는지 확인 |
| `toolAllowlist` | 허용된 Tool만 실행됐는지 확인 |
| `executionModeGate` | `--execute` 없이 변경 Tool이 실행되지 않았는지 확인 |
| `pathSafety` | workspace와 project 경로가 repo 내부인지 확인 |
| `validationCommandAllowlist` | 검증 명령이 `make generate`, `make manifests`, `make test`로 제한됐는지 확인 |
| `deferredToolPolicy` | dry-run에서 실행할 수 없는 Tool이 지연됐는지 확인 |
| `recoveryApprovalGate` | 복구 Tool이 사용자 승인 전 자동 실행되지 않았는지 확인 |

## CPU 환경에서의 의미

GPU가 없는 환경에서는 대형 모델이나 GPU 워크로드 실행보다 Agent 판단의 투명성이 중요하다.

이 구조는 다음을 보여준다.

- RAG 검색과 LLM 판단이 실제로 수행된다.
- LLM은 명령을 직접 실행하지 않는다.
- Tool 실행은 allowlist와 안전 정책을 통과해야 한다.
- 변경 작업은 `--execute`가 있어야만 실행된다.
- 실패 복구는 계획까지만 생성하고 사용자 승인을 기다린다.

따라서 CPU 환경에서도 AI Agent의 핵심인 “검색 기반 판단, 계획 생성, 안전한 Tool 실행, 결과 재평가”를 검증할 수 있다.
