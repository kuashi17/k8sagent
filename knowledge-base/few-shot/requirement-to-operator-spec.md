# Few-Shot: Requirement To Operator Spec

metadata:
- source: internal-authored
- category: few-shot
- use: requirement-planning

## Input Pattern

User writes: `AppConfig라는 Kubernetes Custom Resource를 관리하는 Operator를 만들고 싶다. domain은
beginner.sample.io, group은 app, version은 v1alpha1, kind는 AppConfig로 한다. spec에는 appName:string,
configData:map[string]string, enabled:bool을 포함한다.`

## Expected Planning Output

Extract project domain, API group, version, kind, spec fields, status fields, controller responsibility, and managed
resource. Do not invent missing fields. If managed resource is ConfigMap, recommend an AppConfig profile only when the
profile matches the requirement. The next tools are spec_generator, command_planner, and scaffold_runner dry-run.

## Safety Note

Few-shot values are examples. The Agent must preserve the user's field names and domain values.
