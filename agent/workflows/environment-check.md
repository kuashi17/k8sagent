# Environment Check Workflow

## 목적

Kubebuilder 개발에 필요한 로컬 도구 설치 여부와 버전을 확인하는 흐름을 정의합니다.

## 점검 대상

- `go`
- `docker`
- `kubectl`
- `kind`
- `helm`
- `kubebuilder`
- `kustomize`
- `git`

## 결과 분류

- 설치됨
- 설치되지 않음
- 버전 확인 실패
- 실행 가능하지만 추가 설정 필요

