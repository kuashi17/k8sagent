# Status Update Forbidden

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: status subresource, RBAC

## Symptom

The controller can read the custom resource but fails when updating `.status`. The log includes `forbidden` and the
resource name often ends with `/status`.

## Root Cause

The controller role is missing RBAC for the status subresource. It needs verbs such as `get`, `update`, and `patch` for
`<plural>/status` in the API group.

## Recovery

Add `+kubebuilder:rbac:groups=<group>,resources=<plural>/status,verbs=get;update;patch` to the controller, run
`make manifests`, and reapply the RBAC manifest.
