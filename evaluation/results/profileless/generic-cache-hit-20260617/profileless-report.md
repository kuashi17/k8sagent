# Profile-less Requirement Test Report

- Status: `passed`
- Run level: `fast`
- Created at: `2026-06-17T21:31:29+09:00`

| Requirement | Kind | Managed Resources | Profile Mode | Validated Tools | Result |
|---|---|---|---|---|---|
| `requirements/secret-sync.txt` | `SecretSync` | `Secret` | `none` | `spec_generator, command_planner, scaffold_runner` | `passed` |
| `requirements/scheduled-task.txt` | `ScheduledTask` | `CronJob, Job` | `none` | `spec_generator, command_planner, scaffold_runner` | `passed` |
| `requirements/web-service.txt` | `WebService` | `Deployment, Pod, Service` | `none` | `spec_generator, command_planner, scaffold_runner` | `passed` |

Profile mode `none` means the generic Agent core planned from the requirement without a profile hint.
