# ImagePullBackOff

metadata:
- source: internal-authored
- category: troubleshooting
- appliesTo: pods, workload execution

## Symptom

The controller creates a workload, but the Pod enters `ImagePullBackOff` or `ErrImagePull`. Events mention authentication,
repository not found, pull rate limit, or registry connectivity.

## Root Cause

The image field in the custom resource points to an image that the cluster cannot pull. The Operator reconcile logic may
still be correct if the generated Pod spec contains the requested image.

## Recovery

Verify the image name, tag, registry access, and imagePullSecrets. Do not silently change the image in generated code.
Changing the image is a user-approved sample or requirement update.
