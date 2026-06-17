# Controller Ownership and Watches Guide

metadata:
- source: internal-authored
- category: guide
- topic: owner reference watches

## Owner Reference

Controller가 생성한 하위 리소스에는 ownerReference를 설정하는 것이 일반적이다.
예를 들어 TrainingJob이 Kubernetes Job을 생성하면 Job의 owner를 TrainingJob으로 설정한다.
그러면 TrainingJob 삭제 시 Kubernetes garbage collector가 Job을 함께 정리할 수 있다.

## Watches

Controller-runtime은 기본적으로 Custom Resource 변경을 watch한다.
하위 리소스 변경도 Reconcile을 다시 트리거하려면 `Owns` 또는 watch 설정이 필요하다.
예를 들어 Job 상태 변경에 따라 TrainingJob status를 갱신하려면 Job ownership과 watch가 도움이 된다.

## Agent 판단 기준

요구사항에 “하위 리소스가 함께 정리되어야 한다” 또는 “상태를 하위 리소스 기준으로 갱신한다”가 있으면
Agent는 ownerReference와 watch 필요성을 계획에 포함해야 한다.

