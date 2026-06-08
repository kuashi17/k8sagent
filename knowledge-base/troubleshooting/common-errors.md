# Common Kubebuilder Errors

자주 발생하는 오류와 확인 위치:

- `make: command not found`: make가 설치되어 있지 않다. `make --version`으로 확인한다.
- `controller-gen` 관련 오류: Kubebuilder 프로젝트의 controller-gen 버전과 Go/Kubernetes 라이브러리 버전이 맞지 않을 수 있다.
- `no matches for kind`: CRD가 아직 설치되지 않았거나 API server 등록이 끝나지 않았다. `make install`과 `kubectl get crd`를 확인한다.
- `forbidden`: RBAC 권한이 부족하다. Controller marker와 `config/rbac` manifest를 확인한다.
- `ImagePullBackOff`: 컨테이너 이미지를 가져오지 못했다. 이미지 이름, registry 접근, imagePullSecret을 확인한다.
- `PersistentVolumeClaim not found`: Custom Resource가 참조한 PVC가 존재하지 않는다.
- Pod Pending: 리소스 부족, PVC 미바인딩, node selector 문제 등으로 스케줄링되지 못했다.

Agent는 summary.json과 stdout/stderr 로그를 함께 읽어 실패 단계와 해결 방향을 요약한다.

