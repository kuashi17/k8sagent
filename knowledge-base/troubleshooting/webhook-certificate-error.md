# Webhook Certificate Error

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: admission webhooks, manifests

## Symptom

Webhook-enabled projects fail admission requests because the webhook service certificate is missing, expired, or not
trusted. The API server may report TLS handshake or x509 errors.

## Root Cause

Webhook projects need certificate management and correct service references. Basic Kubebuilder scaffolds without webhook
configuration should not introduce webhook manifests accidentally.

## Recovery

If webhooks are not part of the requirement, keep webhook scaffolding disabled. If webhooks are required, configure
cert-manager or another certificate injection path and verify the service name, namespace, and CA bundle.
