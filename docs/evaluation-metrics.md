# 품질 지표와 측정 방법

## 목적

k8sagent는 “AI가 코드를 만들었다”는 설명만으로 결과를 성공 처리하지 않습니다. 요구사항 해석부터 Controller 산출물, 안전 정책, 빌드·테스트와 실제 Kubernetes lifecycle까지 각 단계의 실행 결과를 수집해 품질을 판단합니다.

이 문서는 다음 내용을 설명합니다.

- 어떤 품질을 측정하는가
- 각 지표를 어떤 실행 결과에서 계산하는가
- Quick·Standard·Full이 각각 어디까지 검증하는가
- `passed`, `failed`, `not-run`을 어떻게 해석해야 하는가
- 현재 측정할 수 없는 업무 성과를 어떻게 구분하는가

## 평가 원칙

1. Local LLM의 설명보다 Tool exit code와 생성 파일을 우선합니다.
2. 컴파일 성공과 Kubernetes 동작 성공을 분리합니다.
3. 실행하지 않은 항목은 성공으로 간주하지 않고 `not-run`으로 남깁니다.
4. Docker·Ollama 같은 환경 오류를 생성 코드 오류와 구분합니다.
5. 서로 다른 범위의 suite 점수는 직접 비교하지 않습니다.
6. 원본 결과와 집계 점수를 함께 남겨 계산 근거를 추적할 수 있게 합니다.

## 현재 자동 측정하는 7개 영역

통합 결과는 [agent/evaluation/unified_evaluation.py](../agent/evaluation/unified_evaluation.py)가 다음 7개 영역으로 정리합니다.

| 영역 | 확인하는 내용 | 주요 근거 |
| --- | --- | --- |
| 요구사항 이해 | API, 필드, 관리·관찰 리소스, 부정 표현과 삭제 정책을 기대한 구조로 추출했는가 | requirement matrix, response consistency matrix |
| RAG 검색 품질 | 관련 guide와 example을 상위 검색 결과에서 찾는가 | Hit@3, Recall@3, MRR |
| Controller 산출물 품질 | CRD, RBAC, Reconcile, status, 멱등성과 삭제 동작이 스펙과 일치하는가 | 생성 프로젝트와 Controller 품질 검사 |
| 빌드·테스트 검증 | Python 단위 테스트와 생성된 Operator의 검증 명령이 성공하는가 | test exit code, `make generate`, `make manifests`, `make test` |
| 안전성·신뢰성 | 허용되지 않은 Tool·경로·명령을 차단하고 오류를 근거에 맞게 분류하는가 | reliability policy tests |
| Kubernetes lifecycle | 생성, 재적용, 변경, drift 복구, 삭제·유지와 외부 watch가 실제 kind에서 동작하는가 | kind matrix evidence |
| 실행시간 | 선택한 suite가 정해진 시간 예산 안에 완료되는가 | check별 elapsed time과 전체 소요 시간 |

## 영역별 계산 방법

### 1. 요구사항 이해

회귀 fixture마다 기대하는 의미 계약과 실제 결과를 비교합니다.

- API domain, group, version, kind
- spec/status 필드명과 타입
- 관리 리소스와 읽기 전용 관찰 리소스
- ownership과 deletion policy
- 리소스별 RBAC verbs
- 금지한 리소스와 쓰기 권한의 미포함
- 필수 정보 누락·타입 불명확·모순의 구조화 오류 코드

같은 요구사항을 반복 처리한 결과는 문장 표현이 아니라 정규화된 계약의 fingerprint로 비교합니다. 모든 fixture가 기대 계약과 일치하고 반복 fingerprint가 같아야 response consistency가 통과합니다.

### 2. RAG 검색 품질

Quick gate는 requirement 질의 7개를 대상으로 다음 기준을 모두 확인합니다.

| 지표 | 통과 기준 |
| --- | ---: |
| Hit@3 | 0.80 이상 |
| Recall@3 | 0.45 이상 |
| MRR | 0.50 이상 |

통합 결과의 RAG 점수는 Hit@3에 100을 곱해 표시하지만, 실제 gate 통과에는 세 지표가 모두 사용됩니다. 25개 전체 질의와 Keyword·Vector·Hybrid 비교는 [RAG 검색 구조와 검증 결과](rag-evaluation.md)에서 별도로 설명합니다.

### 3. Controller 산출물 품질

생성된 Operator마다 다음 7개 기준을 검사합니다.

| 기준 | 확인 내용 |
| --- | --- |
| CRD 정확성 | 기대 kind, spec 필드와 status subresource가 manifest에 반영됨 |
| RBAC 정확성 | Operator 스펙에 필요한 API group과 resource가 Role에 포함됨 |
| Reconcile 동작 | scaffold TODO가 아닌 실제 읽기·생성·갱신 동작이 존재함 |
| status 갱신 | `Status().Update` 또는 `Status().Patch`를 사용함 |
| 멱등성 | CreateOrUpdate 또는 Get 이후 갱신 패턴을 사용함 |
| 삭제 동작 | ownerReference, finalizer 또는 명시적인 retain 정책이 존재함 |
| 테스트 | 생성 프로젝트의 `make test`가 성공함 |

각 기준의 통과 비율을 Controller 점수로 계산하고, 여러 Controller를 실행한 경우 측정된 Controller 점수의 평균을 산출물 품질 점수로 사용합니다.

### 4. 빌드·테스트 검증

저장소 자체의 Agent·LLM·Tool·평가·Web 단위 테스트와 생성된 Controller의 테스트 결과를 집계합니다. 각 명령의 exit code가 `0`이어야 통과합니다.

생성된 Operator는 다음 세 명령을 기본 검증으로 사용합니다.

```text
make generate
make manifests
make test
```

파일이 존재한다는 사실만으로 이 단계를 통과시키지 않습니다. 실제 명령이 실행되지 않았다면 해당 실행 근거는 `not-run`으로 유지합니다.

### 5. 안전성·신뢰성

Reliability gate는 다음과 같은 실패·차단 동작을 검사합니다.

- 잘못된 AI 계획 형식 차단
- 등록되지 않은 Tool과 임의 셸 명령 차단
- 허용되지 않은 make target 차단
- workspace 밖의 경로 차단
- 사용자 승인 없는 execute 차단
- Recovery 자동 실행 차단
- 불명확한 필드 타입의 근거 없는 복구 차단
- Docker 환경 오류의 구조화 분류

안전성 지표는 일부 성공 비율보다 모든 필수 정책의 통과 여부를 우선합니다. 하나라도 실패하면 해당 영역은 `failed`입니다.

### 6. Kubernetes lifecycle

Full suite는 Docker와 kind를 사용해 생성된 Operator의 runtime 동작을 확인합니다.

- Custom Resource와 관리 리소스 생성
- 동일 입력 재적용 시 상태 유지
- spec 변경 반영
- 외부 drift 복구
- status 투영
- RBAC 최소 권한
- CR 삭제 시 managed resource 삭제 또는 retain
- finalizer가 필요한 경우 등록과 정리
- 읽기 전용 외부 리소스 watch

Docker 연결 실패처럼 lifecycle이 시작되지 않은 경우 각 항목은 `not-run`이며 capability 승격 근거로 사용하지 않습니다.

### 7. 실행시간

회귀 runner는 각 check와 전체 suite 시간을 기록합니다.

| Suite | 통합 결과 시간 기준 |
| --- | ---: |
| Quick | 30초 이내 |
| Standard | 180초 이내 |
| Full | 1,200초 이내 |

Full 자동화에서는 통합 관찰 시간 1,200초 외에 핵심 job 실행시간 600초도 별도로 확인합니다. 600초 기준은 코드 생성, 컴파일, Docker와 kind 검증 자체의 성능 회귀를 찾기 위한 값입니다. 1,200초 기준은 runner 대기와 환경 지연까지 포함해 사용자가 관찰하는 전체 시간을 확인하기 위한 값입니다.

실행시간은 하드웨어, Local LLM의 model loading, Go cache와 Docker image 상태에 영향을 받으므로 같은 suite와 유사한 환경의 결과끼리 비교합니다.

## Quick·Standard·Full의 측정 범위

| Suite | 주요 목적 | 추가 환경 | 측정하지 않는 항목 |
| --- | --- | --- | --- |
| `quick` | 코드 회귀, RAG gate, 결정론적 응답 일관성, 안전 정책 | Python | 실제 Local LLM 반복 실행, compile matrix, kind lifecycle |
| `standard` | Quick + Local LLM을 포함한 실제 Agent 흐름 | Ollama | compile matrix, kind lifecycle |
| `full` | Standard + 여러 요구사항의 코드 생성·컴파일·kind lifecycle | Ollama, Go, Docker, kind | 없음 |

Quick 결과가 통과했더라도 Kubernetes lifecycle까지 검증됐다는 뜻은 아닙니다. 반대로 Quick의 `final-evaluation.json`에서 Full 전용 영역이 `not-run`인 것은 실패가 아니라 실행 범위의 차이입니다.

## 상태와 점수 해석

| 상태 | 의미 |
| --- | --- |
| `passed` | 해당 suite에서 실행하기로 한 필수 검사가 모두 통과함 |
| `failed` | 실행한 필수 검사 중 하나 이상이 실패함 |
| `not-run` | 해당 suite에 포함되지 않았거나 필요한 환경이 없어 실행하지 못함 |

회귀 성공 여부의 1차 기준은 `regression-summary.json`의 check exit code입니다. `final-evaluation.json`은 여러 결과를 한 화면에서 보기 위한 보조 집계입니다.

`overallScore`는 7개 영역의 단순 평균이고 `not-run`은 0점으로 포함됩니다. 따라서 Quick와 Full의 전체 점수를 비교하면 안 되며, 점수를 단독 품질 보증 값으로 사용하지 않습니다. 같은 suite의 영역별 원본 결과와 실행 범위를 함께 확인해야 합니다.

## 실행 방법

```bash
# Python만으로 빠른 회귀
python3 scripts/run-regression-tests.py \
  --suite quick \
  --output-dir evaluation/results/regression/local-quick

# Local LLM 포함
python3 scripts/run-regression-tests.py \
  --suite standard \
  --output-dir evaluation/results/regression/local-standard

# Local LLM, compile과 kind lifecycle 포함
python3 scripts/run-regression-tests.py \
  --suite full \
  --output-dir evaluation/results/regression/local-full
```

## 주요 결과 파일

| 파일 | 내용 |
| --- | --- |
| `regression-summary.json` | 실행한 check, 명령, exit code와 소요 시간 |
| `final-evaluation.json` | 7개 품질 영역의 상태와 보조 점수 |
| `performance-trend.json` | 현재와 이전 실행의 check별 소요 시간 |
| `rag-quality.json` | Quick RAG gate의 질의별 결과와 지표 |
| `response-consistency.json` | 요구사항 의미 계약의 정확성과 반복 일관성 |
| `reliability/reliability-test-results.json` | Tool·경로·실행·복구 안전 정책 결과 |
| `compile-matrix/compile-matrix-results.json` | 생성 Operator별 compile·Controller 품질 결과 |
| `kind-matrix/kind-matrix-results.json` | 실제 Kubernetes lifecycle evidence |
| `capability-matrix.json` | compile과 kind 근거를 합친 리소스별 검증 수준 |

결과 파일은 `evaluation/results/` 아래에 생성되며 기본적으로 Git에 누적하지 않습니다.

## 업무 성과 지표와 현재 한계

개발 자동화의 업무 효과를 설명하려면 다음 항목도 필요합니다.

- 수작업 대비 요구사항 작성부터 검증 완료까지의 시간 단축률
- 추가 수정 없이 첫 검증을 통과한 작업의 비율
- 사용자가 오류 원인과 다음 조치를 확인하기까지 걸린 시간
- 초보 사용자의 작업 완료율과 추가 질문 횟수

현재 저장소에는 동일한 과제를 수작업과 k8sagent로 반복 측정한 확정 baseline이 없습니다. 따라서 수작업 2시간 같은 임의 값으로 시간 단축률을 계산하거나 업무 성과로 주장하지 않습니다.

이 항목을 측정하려면 같은 요구사항, 같은 장비와 같은 완료 기준으로 수작업·k8sagent 실행을 각각 여러 번 수행해야 합니다. Web의 `journeyTimings`는 자동 처리, 승인 대기와 전체 사용자 여정을 구분하므로 향후 실제 사용자 측정의 근거로 사용할 수 있습니다.
