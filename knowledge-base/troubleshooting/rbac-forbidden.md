# RBAC Forbidden

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: controller runtime, Kubernetes API permissions

## Symptom

The controller logs show `forbidden`, `cannot get`, `cannot list`, `cannot create`, `cannot update status`, or a
Kubernetes API request is denied. The reconcile loop may retry without creating or updating the expected resource.

## Root Cause

The generated ClusterRole does not include the resource or verb required by the controller. Status updates usually need
`<resource>/status` with `get`, `update`, and `patch`. Child resources such as ConfigMap, StatefulSet, Job, Pod, PVC,
or Service require verbs that match the controller behavior.

## Recovery

Add or correct `+kubebuilder:rbac` markers, then run `make manifests` and redeploy the RBAC manifest. Prefer deriving
markers from `operator-spec.yaml` `rbac.resources` so the generated controller code and manifest stay aligned.
