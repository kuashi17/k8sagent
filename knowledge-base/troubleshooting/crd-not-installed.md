# CRD Not Installed

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: kubectl apply, kind e2e

## Symptom

`kubectl apply -f config/samples/...yaml` fails with `no matches for kind`, or `kubectl get <plural>` fails because the
custom resource type is unknown.

## Root Cause

The CRD under `config/crd/bases` has not been installed into the current Kubernetes cluster, or `kubectl` is pointing at
the wrong context.

## Recovery

Verify `kubectl config current-context`, then run `make install` or apply the CRD manifest. Confirm registration with
`kubectl get crd | grep <plural>`. Only apply sample custom resources after the CRD is established.
