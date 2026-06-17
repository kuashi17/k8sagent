# Project Initialization Guide

metadata:
- source: internal-authored
- category: guide
- topic: kubebuilder project initialization

## Purpose

Kubebuilder 프로젝트 초기화는 Operator 개발 작업 공간을 만드는 첫 단계다.
Agent는 이 문서를 사용해 `kubebuilder init` 명령을 언제 실행해야 하는지,
Go module 경로와 domain 값이 준비됐는지 판단한다.

## Required Inputs

프로젝트 초기화에는 최소한 `project.domain`과 `project.module`이 필요하다.
domain은 CRD API group suffix로 사용되고, module은 Go module path로 사용된다.
예를 들어 domain이 `beginner.sample.io`이고 프로젝트 이름이 `app-config-operator`이면
module은 `beginner.sample.io/app-config-operator`처럼 잡을 수 있다.

## Command Pattern

```bash
kubebuilder init --domain <domain> --repo <module>
```

이 명령은 `PROJECT`, `Makefile`, `cmd/main.go`, `config/manager`,
`config/default`, Go module 파일을 생성한다. 이미 디렉터리가 존재하면
덮어쓰기 위험이 있으므로 scaffold runner는 기본적으로 중단해야 한다.

## Validation

초기화 후에는 `PROJECT` 파일에 domain이 반영됐는지,
`go.mod` module이 요구사항과 일치하는지 확인한다. 문제가 있으면 이후
`kubebuilder create api`와 `make generate`에서 연쇄 오류가 발생할 수 있다.

