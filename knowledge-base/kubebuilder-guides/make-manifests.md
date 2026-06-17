# make manifests Guide

metadata:
- source: internal-authored
- category: guide
- topic: make manifests crd rbac

## Purpose

`make manifests`는 CRD, RBAC, webhook 관련 manifest를 생성한다.
MVP에서는 CRD schema와 RBAC role 생성 여부가 핵심 검증 대상이다.

## Inputs

- API type markers
- Controller RBAC markers
- PROJECT 파일
- controller-gen binary

## Common Failures

RBAC marker 문법이 잘못됐거나 API group/resource 이름이 틀리면 role manifest가 의도와 다르게 생성된다.
CRD marker가 잘못되면 `config/crd/bases` schema 생성에 실패할 수 있다.

## Verification

`config/rbac/role.yaml`에 관리 대상 리소스와 verbs가 포함됐는지 확인한다.
`config/crd/bases/*.yaml`에 spec/status schema가 반영됐는지 확인한다.

