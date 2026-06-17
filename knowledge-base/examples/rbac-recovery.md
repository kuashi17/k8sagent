# RBAC Recovery Example

metadata:
- source: internal-authored
- category: example
- scenario: recovery

## Situation

An AppConfig controller creates ConfigMaps, but the deployed controller logs `configmaps is forbidden`. The generated
RBAC role does not include `core/configmaps` create/update/patch permissions.

## Correct Recovery Plan

Add `core/configmaps` to `operator-spec.yaml` `rbac.resources` with verbs that match the controller behavior. Then patch
the controller RBAC markers, run `make manifests`, and redeploy the RBAC manifest. If status updates fail, also check
`appconfigs/status`.
