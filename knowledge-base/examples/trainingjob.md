# TrainingJob Example

TrainingJob은 GPU 학습 도메인을 대상으로 한 MVP 검증 profile이다.

요구사항 핵심:

- Custom Resource: `TrainingJob`
- 관리 리소스: Kubernetes `Job`
- 참조 리소스: `Pod`, `PersistentVolumeClaim`
- `spec.image`는 Job container image로 사용한다.
- `spec.gpuCount`는 `nvidia.com/gpu` limit으로 반영한다.
- `spec.pvcName`은 `/workspace` PVC mount에 사용한다.
- `spec.datasetPath`, `spec.outputPath`는 환경변수로 전달한다.

kind 클러스터에는 GPU가 없을 수 있으므로 GPU 부족으로 인한 Pod Pending은 Job spec 검증이 성공했다면 warning으로 처리할 수 있다.

