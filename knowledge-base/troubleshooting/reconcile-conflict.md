# Reconcile Conflict

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: controller-runtime, status updates

## Symptom

The controller logs contain `the object has been modified; please apply your changes to the latest version and try
again`. Status may lag behind resource state.

## Root Cause

The controller is updating an object based on an older resourceVersion. This is common when spec/status updates happen
quickly or multiple reconcilers touch the same object.

## Recovery

Fetch the latest object before updating status, use `client.Status().Patch` or retry on conflict, and keep spec updates
separate from status updates. Do not treat a single conflict as a permanent failure.
