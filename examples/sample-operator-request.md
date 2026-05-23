# Sample Operator Request

## 자연어 요구사항 예시

BackupPolicy라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다.

BackupPolicy는 대상 namespace, 스케줄, 보관 기간, 백업 대상 PVC 목록을 spec으로 가진다.

status에는 마지막 백업 시간, 성공 여부, 실패 사유를 기록한다.

Controller는 BackupPolicy 변경을 감지하고 백업 Job 생성을 조정해야 한다.

## 구조화 스펙 예시

| 항목 | 값 |
| --- | --- |
| Resource | BackupPolicy |
| API Group | backup.example.com |
| Version | v1alpha1 |
| Kind | BackupPolicy |
| Spec | targetNamespace, schedule, retentionDays, pvcNames |
| Status | lastBackupTime, succeeded, failureReason |
| Reconcile 책임 | BackupPolicy 감지, 백업 Job 생성, 상태 업데이트 |
| RBAC 범위 | BackupPolicy, Job, PVC 조회 및 Job 생성/수정 |

