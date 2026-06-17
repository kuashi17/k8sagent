# API and CRD Design Guide

metadata:
- source: internal-authored
- category: guide
- topic: api crd design

## Purpose

API 설계는 사용자가 Kubernetes에 어떤 Custom Resource를 만들지 정의하는 단계다.
Agent는 자연어 요구사항에서 domain, group, version, kind, spec, status를 추출해
`operator-spec.yaml`의 API 구조로 변환한다.

## Required Fields

CRD 설계에는 다음 값이 중요하다.

- `domain`: 조직 또는 샘플 도메인
- `group`: API group의 앞부분
- `version`: 보통 MVP에서는 `v1alpha1`
- `kind`: Custom Resource 이름
- `specFields`: 사용자가 원하는 상태
- `statusFields`: Controller가 관찰한 상태

## Kubebuilder Command

```bash
kubebuilder create api \
  --group <group> \
  --version <version> \
  --kind <Kind> \
  --resource \
  --controller
```

`--resource`는 CRD 타입 생성을 의미하고, `--controller`는 Reconcile scaffold 생성을 의미한다.
둘 중 하나가 빠지면 산출물이 부족해질 수 있다.

## CRD Review

`make manifests` 이후 `config/crd/bases` 아래 CRD YAML에 spec/status schema가 반영됐는지 확인한다.
필드 타입이 잘못되면 controller-gen 단계에서 실패하거나 CRD schema가 의도와 다르게 생성된다.

