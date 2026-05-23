# Requirement Analysis Prompt

## 목적

사용자의 자연어 Operator 요구사항을 Kubebuilder 개발에 필요한 구조화 스펙으로 변환하기 위한 프롬프트 초안입니다.

## 입력

- 사용자 자연어 요구사항
- 대상 도메인
- 필요한 Kubernetes 리소스
- 배포 및 검증 환경

## 출력 형식

- Resource 이름
- API group
- Version
- Kind
- Spec 필드
- Status 필드
- Reconcile 책임
- RBAC 필요 범위
- 테스트 필요 항목
- 추가 확인 질문

