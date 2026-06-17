# Kind E2E Flow Guide

metadata:
- source: internal-authored
- category: guide
- topic: kind e2e

## Purpose

kind e2e는 생성된 Operator가 실제 Kubernetes API server에서 동작하는지 확인하는 단계다.
로컬 Docker 기반 kind cluster를 사용한다.

## Typical Flow

1. kind cluster 존재 여부 확인
2. 없으면 cluster 생성
3. CRD 설치
4. Controller 실행 또는 배포
5. sample Custom Resource 적용
6. 하위 리소스 생성 확인
7. status 갱신 확인
8. summary.json 저장

## Warning Policy

GPU가 없는 kind cluster에서 `Insufficient nvidia.com/gpu`로 Pod가 Pending이면,
Job spec 검증이 성공한 경우 Operator 오류가 아니라 환경 warning으로 볼 수 있다.

