# PVC Not Found

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: workloads, volume mounts, e2e

## Symptom

A Pod remains Pending or ContainerCreating and events mention `persistentvolumeclaim "<name>" not found`. A controller
may have created the Job, StatefulSet, or Pod correctly, but the referenced volume does not exist in the namespace.

## Root Cause

The sample custom resource references `spec.pvcName`, but the corresponding PersistentVolumeClaim was not created, was
created in a different namespace, or has a different name.

## Recovery

Create the sample PVC before applying the custom resource, or update the sample to reference an existing PVC. This is
usually a sample/environment issue, not a controller code issue, when the generated workload contains the expected
claimName.
