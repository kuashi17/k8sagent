# Current MVP Status

## 현재 완료된 기능

- 범용 Operator 요구사항 작성 템플릿 작성
- 자연어 요구사항을 `operator-spec.yaml`로 변환하는 `spec_generator.py` 구현
- `operator-spec.yaml` 기반 Kubebuilder command plan 생성
- `scaffold_runner.py` 기반 dry-run, preflight, execute 실행
- Kubebuilder scaffold 생성
- `artifact_patcher.py` 기반 API 타입, sample YAML, RBAC marker 보정
- TrainingJob Controller Reconcile 로직 구현
- `make generate`, `make manifests`, `make test` 검증
- kind 기반 e2e runner 구현
- clean e2e 재검증 구현
- Job spec validation 구현
- `log_analyzer.py` 기반 성공/경고 분석 리포트 생성
- LangChain-style Agent Orchestrator 구현
- 기존 CLI 도구를 Agent Tool wrapper로 호출하는 구조 구현
- 로컬 Markdown `knowledge-base` 기반 RAG 검색 구현
- Agent 기반 requirement dry-run 구현
- Agent 기반 e2e 로그 분석과 GPU Pending warning 자연어 판단 구현
- core/profile 구조 문서화
- TrainingJob, RedisCache profile YAML 초안 작성

## 검증 완료된 로그 경로

| 단계 | 로그 경로 | 결과 |
| --- | --- | --- |
| scaffold | `logs/scaffold/` | Kubebuilder scaffold 및 generate/manifests/test 성공 로그 저장 |
| patch | `logs/patch/` | API 타입, sample, RBAC 보정 및 검증 성공 로그 저장 |
| clean e2e | `logs/e2e/20260607-213346/summary.json` | 성공, GPU Pending warning |
| log analysis | `logs/e2e/20260607-213346/analysis.md` | 성공 분석 리포트 생성 |
| Agent requirement dry-run | `logs/agent/20260608-225601/agent-report.md` | AppConfig 요구사항 요약, RAG 검색, Tool dry-run 성공 |
| Agent log analysis | `logs/agent/20260608-230117/agent-report.md` | TrainingJob e2e 로그를 `succeeded-with-warning`으로 판단 |

## clean e2e 결과 요약

실행 명령:

```bash
python3 agent/tools/e2e_runner.py \
  --input generated/trainingjob-operator-spec.yaml \
  --clean \
  --execute
```

결과:

- kind 클러스터 `trainingjob-e2e` 확인 성공
- CRD 설치 성공
- 기존 TrainingJob/Job/Pod 삭제 및 삭제 확인 성공
- sample PVC 적용 성공
- Controller 실행 성공
- sample TrainingJob CR 적용 성공
- Kubernetes Job `trainingjob-sample-job` 생성 확인
- TrainingJob status 갱신 확인
- `failedStep: null`

Job spec validation:

| 항목 | 기대값 | 실제값 | 결과 |
| --- | --- | --- | --- |
| container image | `busybox:latest` | `busybox:latest` | passed |
| GPU limit | `1` | `1` | passed |
| PVC claimName | `sample-pvc` | `sample-pvc` | passed |
| `/workspace` volumeMount | `workspace` | `workspace` | passed |
| `DATASET_PATH` | `/workspace/dataset` | `/workspace/dataset` | passed |
| `OUTPUT_PATH` | `/workspace/output` | `/workspace/output` | passed |

Pod 상태:

- Pod phase: `Pending`
- 원인: `Insufficient nvidia.com/gpu`
- 처리: kind 환경의 GPU 리소스 부족이므로 warning으로 분류

Agent 로그 분석 결과:

```bash
python3 agent/langchain_agent.py \
  --analyze-log logs/e2e/20260607-213346 \
  --planner mock
```

- `log_analyzer.py` Tool 호출 성공
- `analysis.md`와 `summary.json` 읽기 성공
- `knowledge-base/examples/trainingjob.md`, `knowledge-base/troubleshooting/common-errors.md` 등 RAG 검색
- Decision: `succeeded-with-warning`
- Classification: `succeeded-with-gpu-pending-warning`
- 판단: Controller가 Job을 생성하지 못한 오류가 아니라, kind 클러스터에 `nvidia.com/gpu` 리소스가 없어 Pod가 Pending인 케이스

TrainingJob status:

```json
{
  "phase": "Running",
  "jobName": "trainingjob-sample-job",
  "podName": "trainingjob-sample-job-j4lp2",
  "message": "TrainingJob is running"
}
```

## 현재 한계

- `e2e_runner.py`에 TrainingJob Job/GPU/PVC 검증 로직이 직접 포함되어 있음
- `artifact_patcher.py`에 sample 값과 RBAC 보강 로직이 profile과 분리되어 있지 않음
- `log_analyzer.py`의 추천 명령과 evidence 수집 일부가 TrainingJob 흐름에 묶여 있음
- RAG는 현재 로컬 Markdown 검색이며 Vector DB/Reranker는 아직 미적용
- LLM 기반 Semantic Parsing은 아직 미적용이며 현재 planner는 규칙 기반 `mock` 모드
- Jenkins, Harbor, Argo CD 연계는 문서화 단계
- 실패 로그 분석은 규칙 기반이며, 더 많은 실패 사례 축적이 필요함

## 남은 과제

- `e2e_runner.py`를 core runner와 profile validation으로 분리
- `artifact_patcher.py`의 sample/RBAC profile hook 설계
- `log_analyzer.py`의 profile별 warning/evidence rule 분리
- PVC not found, ImagePullBackOff, RBAC forbidden 등 의도적 실패 시나리오 검증
- RedisCache profile 기반 e2e 시나리오 추가
- 문서화된 profile 구조를 실제 코드 로딩 구조로 연결
- `mock` planner를 ChatOpenAI 또는 로컬 LLM planner로 교체할 수 있는 실행 모드 확장
- RAG 검색을 Vector DB와 Reranker 기반으로 고도화

## 2차 확장 항목

- LLM 기반 요구사항 Semantic Parsing
- RAG 기반 Kubebuilder 문서와 사내 예제 검색
- Reranker 기반 참조 문서 선별
- Few-shot 기반 산출물 생성 품질 개선
- Jenkins 검증 로그 수집
- Harbor 이미지 빌드/푸시 확인
- Argo CD 배포 Sync/Health 확인
- GitHub branch, commit, PR 초안 자동화
- 오류 유형 축적 기반 프롬프트와 생성 규칙 개선
