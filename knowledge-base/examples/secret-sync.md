# SecretSync Operator Example

SecretSync is a requirement fixture for an Operator that reads a source Secret and reconciles a destination Secret in another namespace.

The API should describe source and destination names and namespaces. The Controller needs read permission for the source Secret and create, update, patch, and delete permission for destination Secrets. Status should record the last synchronized resource version and phase.

Use owner references only when the destination is in the same namespace. Cross-namespace resources cannot use a namespaced owner reference, so cleanup needs an explicit finalizer policy.
