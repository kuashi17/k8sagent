# Envtest Guide

metadata:
- source: internal-authored
- category: guide
- topic: envtest make test

## Purpose

envtest는 Controller 테스트에서 API server와 etcd를 로컬로 실행하기 위한 테스트 환경이다.
Kubebuilder scaffold의 `make test`는 envtest binary를 요구할 수 있다.

## Common Failure

`setup-envtest` 또는 envtest binary가 없다는 오류가 나오면 Kubernetes envtest assets 설치가 필요하다.
이 문제는 Operator 로직 오류가 아니라 테스트 환경 문제로 분류한다.

## Recovery

Agent는 envtest 누락을 발견하면 테스트 환경 설치 또는 Makefile의 envtest 설정 확인을 제안한다.
코드 patch보다 환경 준비가 먼저다.

