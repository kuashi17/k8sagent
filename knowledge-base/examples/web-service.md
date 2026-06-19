# WebService Operator Example

WebService is a requirement fixture for an Operator that manages a Deployment and Service.

The spec contains image, replicas, containerPort, and servicePort. Reconcile should create or update both resources, use a stable label selector, set owner references, and expose readiness through status.

Lifecycle validation should cover initial creation, replica or image update, deletion of owned resources, and restoration of the sample Custom Resource.
