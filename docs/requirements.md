# Requirements Structuring Guide

## 목적

이 문서는 자연어로 입력된 Operator 개발 요구사항을 Kubebuilder 기반 개발에 필요한 구조화 스펙으로 변환하기 위한 기준을 정의합니다.

## 구조화 대상

| 항목 | 설명 |
| --- | --- |
| Resource 목적 | Operator가 관리할 도메인 객체와 업무 목적 |
| API Group | Kubernetes API group |
| Version | API version |
| Kind | Custom Resource kind |
| Spec Fields | 사용자가 선언하는 원하는 상태 |
| Status Fields | Controller가 기록하는 실제 상태 |
| Reconcile 책임 | Controller가 감지하고 수행해야 하는 작업 |
| RBAC 범위 | 조회, 생성, 수정, 삭제가 필요한 Kubernetes 리소스 |
| Manifest 범위 | 배포에 필요한 CRD, RBAC, Manager, Webhook 등 |
| Test 범위 | 기본 단위 테스트 및 Reconcile 동작 검증 항목 |

## 요구사항 분석 질문

- 이 Operator가 관리하려는 Custom Resource는 무엇인가?
- 사용자가 `spec`에 선언해야 하는 필드는 무엇인가?
- Controller가 `status`에 기록해야 하는 필드는 무엇인가?
- Reconcile 루프에서 생성하거나 수정해야 하는 외부 리소스는 무엇인가?
- 어떤 Kubernetes 리소스에 대한 RBAC 권한이 필요한가?
- 배포 대상은 로컬 kind 클러스터인가, 운영 클러스터인가?
- 테스트에서 반드시 확인해야 하는 성공 조건은 무엇인가?

## 산출물

요구사항 분석 결과는 `generated` 디렉터리에 구조화 스펙 형태로 저장하는 것을 목표로 합니다.

## 관련 템플릿

- [Operator Requirement Template](operator-requirement-template.md)
- [Requirement Writing Guide](requirement-writing-guide.md)
- [Plain Text Template](../requirements/template.txt)
