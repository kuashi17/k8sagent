# ScheduledTask Operator Example

ScheduledTask is a requirement fixture for an Operator that creates and updates a Kubernetes CronJob.

The Custom Resource contains schedule, image, command, suspend, and history limit fields. The Controller owns a CronJob, copies the schedule and Pod template fields, and reports the active CronJob name and phase in status.

The Controller needs batch API permissions for cronjobs and jobs. Lifecycle validation should cover create, schedule update, suspend, delete, and restore.
