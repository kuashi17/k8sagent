# RAG Evaluation

## 목적

이 문서는 Kubebuilder Operator Agent의 RAG 검색 품질을 정량 평가하는 방법을 설명한다.

Agent는 `knowledge-base/` 아래 Markdown 문서를 검색해 LLM planner 입력으로 사용한다. 따라서 검색 결과가 적절한 문서를 상위에 올리는지 확인해야 한다. 평가기는 같은 질의 세트를 `keyword`, `vector`, `hybrid`, `hybrid-rerank` 모드로 실행하고 지표를 비교한다.

## Knowledge Base 구조

현재 Knowledge Base는 다음 범주로 구성된다.

- `knowledge-base/kubebuilder-guides/`: Kubebuilder 개발 흐름, CRD 설계, RBAC, Reconcile, make 검증, kind e2e
- `knowledge-base/troubleshooting/`: controller-gen, make generate/manifests, RBAC, PVC, ImagePullBackOff, GPU 부족, envtest 등 오류 대응
- `knowledge-base/examples/`: AppConfig, TrainingJob, RedisCache, 복구 예시, GPU Pending 분석 예시
- `knowledge-base/few-shot/`: 요구사항 변환, Tool 계획, 최종 평가, 복구 계획, warning/failure 분류 예시

문서는 내부 작성 문서이며, 각 문서 상단에 metadata를 포함한다.

## 검색 모드

| Mode | 설명 | 기본 사용 여부 |
| --- | --- | --- |
| `keyword` | Markdown 문서에서 키워드가 많이 맞는 문서를 반환 | fallback 및 비교용 |
| `vector` | Ollama embedding과 FAISS index로 의미 기반 검색 | 비교용 |
| `hybrid` | vector와 keyword 점수를 결합 | CPU 기본값 |
| `hybrid-rerank` | hybrid 후보를 Local LLM으로 재정렬 | 별도 검증용 |

CPU 환경 기본값:

```bash
export RAG_MODE=hybrid
export RAG_RERANK_ENABLED=false
```

reranker 검증 시:

```bash
export RAG_MODE=hybrid-rerank
export RAG_RERANK_ENABLED=true
export LOCAL_LLM_TIMEOUT_SECONDS=120
```

## 평가 데이터셋

평가 데이터셋은 `evaluation/rag-evaluation-dataset.yaml`이다.

각 질의는 다음 정보를 가진다.

- `id`: 평가 항목 식별자
- `query`: 검색 질의
- `category`: requirement, generation, validation, troubleshooting, recovery, environment-warning
- `expectedSources`: 상위 검색 결과에 나와야 하는 문서
- `expectedKeywords`: 의미 검증용 키워드
- `notes`: 평가 의도

데이터셋은 AppConfig ConfigMap, TrainingJob GPU limit, RedisCache StatefulSet/Service, invalid field type, controller-gen failure, make generate/manifests failure, RBAC forbidden, PVC not found, ImagePullBackOff, insufficient GPU, status update, finalizer, envtest, kind e2e 질의를 포함한다.

## 평가 지표

| Metric | 의미 |
| --- | --- |
| Hit@1 | 첫 번째 결과가 정답 문서인지 여부의 평균 |
| Hit@3 | 상위 3개 안에 정답 문서가 있는지 여부의 평균 |
| Recall@3 | 정답 문서 중 상위 3개에 포함된 비율의 평균 |
| Recall@5 | 정답 문서 중 상위 5개에 포함된 비율의 평균 |
| MRR | 첫 정답 순위의 reciprocal rank 평균 |
| Avg Latency | 질의당 평균 검색 시간 |
| P95 Latency | 검색 시간의 95 percentile |
| Fallback Count | vector/hybrid 실패 후 fallback이 발생한 횟수 |
| Reranker Timeout Count | reranker timeout 또는 timeout성 fallback 횟수 |

## 실행 방법

기본 평가:

```bash
./scripts/evaluate-rag.sh
```

직접 실행:

```bash
python3 agent/rag/build_index.py \
  --knowledge-base knowledge-base \
  --index-dir knowledge-base/.index \
  --rebuild

python3 agent/evaluation/rag_evaluator.py \
  --dataset evaluation/rag-evaluation-dataset.yaml \
  --index-dir knowledge-base/.index \
  --modes keyword,vector,hybrid \
  --output-dir evaluation/results
```

reranker 별도 검증:

```bash
python3 agent/evaluation/rag_evaluator.py \
  --dataset evaluation/rag-evaluation-dataset.yaml \
  --index-dir knowledge-base/.index \
  --modes hybrid-rerank \
  --reranker-timeout 120 \
  --output-dir evaluation/results
```

## 결과 파일

결과는 `evaluation/results/<timestamp>/` 아래에 생성된다.

- `evaluation-summary.json`: 모드별 집계 지표
- `evaluation-details.json`: 질의별 상세 결과
- `keyword-results.json`
- `vector-results.json`
- `hybrid-results.json`
- `hybrid-rerank-results.json`
- `rag-evaluation-report.md`: 사람이 읽는 Markdown 리포트

## Few-Shot Context 정책

Requirement planning에서는 guide/reference 문서를 최대 2개, example 또는 few-shot 문서를 최대 1개 선택한다.

Recovery planning에서는 troubleshooting/reference 문서를 최대 2개, recovery few-shot을 최대 1개 선택한다.

Agent는 `selected-context.json` 또는 Agent summary에 다음 정보를 기록한다.

```json
{
  "contextType": "reference | few-shot",
  "sourcePath": "knowledge-base/...",
  "reason": "why this context was selected"
}
```

Few-shot 문서는 형식과 판단 예시로만 사용한다. 사용자 requirement의 domain, kind, field 이름을 few-shot 값으로 덮어쓰면 안 된다.
