# RedisCache Operator Example

metadata:
- source: internal-authored
- category: example
- profile: rediscache

## Requirement Pattern

RedisCache manages a Redis StatefulSet and a Service. The custom resource usually includes fields such as `size`,
`image`, and `storageSize`. The status can include `phase`, `readyReplicas`, and `message`.

## Reconcile Pattern

The controller creates or updates a StatefulSet named from the RedisCache resource. The StatefulSet uses
`spec.size` for replicas, `spec.image` for the Redis container image, and a `volumeClaimTemplates` entry for persistent
storage. A Service exposes port `6379` and uses the same Pod labels as the StatefulSet selector.

## RBAC Pattern

The controller needs access to StatefulSets, Services, Pods, PersistentVolumeClaims, and the RedisCache status
subresource. The StatefulSet and Service permissions need create/update/patch/delete when the controller owns them.
