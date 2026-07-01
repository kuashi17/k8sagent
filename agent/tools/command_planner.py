#!/usr/bin/env python3
"""Create a Kubebuilder command plan from a generated Operator spec.

This tool does not execute any command. It only renders a reviewable
Markdown plan that can be used by the next Agent workflow step.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.error_taxonomy import ErrorCode, emit_tool_error


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Kubebuilder command plan from operator-spec.yaml.")
    parser.add_argument("--input", required=True, help="Path to generated operator spec YAML.")
    parser.add_argument("--output", required=True, help="Path to write command plan Markdown.")
    parser.add_argument(
        "--workspace",
        default="workspace/generated-operators",
        help="Scaffold workspace parent used to explain the final target directory when project.workspace is not set.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    spec = load_spec(input_path)
    errors = spec.get("errors") or []
    if errors:
        print("Cannot create command plan because operator spec has errors:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        emit_tool_error(
            ErrorCode.REQUIRED_INPUT_MISSING,
            "; ".join(str(item) for item in errors),
            stage="command-planning",
        )
        return 2

    model = normalize_spec(spec, args.workspace)
    missing = required_missing(model)
    if missing:
        print("Cannot create command plan because required fields are missing:", file=sys.stderr)
        for field in missing:
            print(f"- {field}", file=sys.stderr)
        emit_tool_error(
            ErrorCode.REQUIRED_INPUT_MISSING,
            "Missing required fields: " + ", ".join(missing),
            stage="command-planning",
        )
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_plan(model, spec), encoding="utf-8")
    print(f"Command plan written: {output_path}")
    return 0


def load_spec(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"operator spec not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"operator spec must be a YAML mapping: {path}")
    return data


def normalize_spec(spec: dict[str, Any], scaffold_workspace_parent: str) -> dict[str, Any]:
    project = spec.get("project") or {}
    api = spec.get("api") or {}
    resource = spec.get("resource") or {}
    controller = spec.get("controller") or {}
    validation = spec.get("validation") or {}

    name = project.get("name") or infer_project_name(api.get("kind") or resource.get("kind", ""))
    domain = project.get("domain") or api.get("domain") or infer_domain(resource.get("apiGroup", ""), resource.get("group", ""))
    module = project.get("module") or (f"{domain}/{name}" if domain and name else "")
    workspace = project.get("workspace") or (f"workspace/{name}" if name else "workspace/<project-name>")
    directory_name = Path(project.get("workspace", "")).name if project.get("workspace") else name
    final_target_dir = str(Path(scaffold_workspace_parent) / directory_name) if directory_name else str(Path(scaffold_workspace_parent) / "<project-name>")

    group = api.get("group") or resource.get("group", "")
    version = api.get("version") or resource.get("version", "")
    kind = api.get("kind") or resource.get("kind", "")

    return {
        "project": {
            "name": name,
            "module": module,
            "domain": domain,
            "workspace": workspace,
            "directoryName": directory_name,
            "scaffoldWorkspaceParent": scaffold_workspace_parent,
            "finalTargetDir": final_target_dir,
        },
        "api": {
            "group": group,
            "version": version,
            "kind": kind,
        },
        "controllerEnabled": bool(controller.get("enabled", True)),
        "validationCommands": validation.get("commands") or ["make generate", "make manifests", "make test"],
    }


def required_missing(model: dict[str, Any]) -> list[str]:
    checks = {
        "project.name": model["project"].get("name"),
        "project.module": model["project"].get("module"),
        "project.domain": model["project"].get("domain"),
        "api.group": model["api"].get("group"),
        "api.version": model["api"].get("version"),
        "api.kind": model["api"].get("kind"),
    }
    return [name for name, value in checks.items() if not value]


def render_plan(model: dict[str, Any], spec: dict[str, Any]) -> str:
    project = model["project"]
    api = model["api"]
    warnings = spec.get("warnings") or []
    controller_flag = "--controller" if model["controllerEnabled"] else "--controller=false"

    lines = [
        f"# Kubebuilder Command Plan: {api['kind']}",
        "",
        "## Project Info",
        "",
        f"- `project.name`: `{project['name']}`",
        f"- `project.module`: `{project['module']}`",
        f"- `project.domain`: `{project['domain']}`",
        f"- `api.group`: `{api['group']}`",
        f"- `api.version`: `{api['version']}`",
        f"- `api.kind`: `{api['kind']}`",
        f"- Spec-defined workspace: `{project['workspace']}`",
        f"- Scaffold workspace parent: `{project['scaffoldWorkspaceParent']}`",
        f"- Final target project directory: `{project['finalTargetDir']}`",
        "",
        "## Workspace Path Guide",
        "",
        "- `Spec-defined workspace`는 스펙에 기록된 기본 작업 경로입니다.",
        "- `Scaffold workspace parent`는 `scaffold_runner.py --workspace`에 전달하는 상위 폴더입니다.",
        "- `Final target project directory`가 실제 Kubebuilder 프로젝트가 생성될 위치입니다.",
        "- 초보자는 최종적으로 `Final target project directory`만 확인하면 됩니다.",
        "",
    ]

    if warnings:
        lines.extend(
            [
                "## Warnings",
                "",
                *[f"- {warning}" for warning in warnings],
                "",
            ]
        )

    lines.extend(
        [
            "## Kubebuilder Command Plan",
            "",
            "1. Create workspace directory",
            "",
            "   ```bash",
            f"   mkdir -p {project['finalTargetDir']}",
            "   ```",
            "",
            "2. Initialize Kubebuilder project",
            "",
            "   ```bash",
            f"   cd {project['finalTargetDir']}",
            f"   kubebuilder init --domain {project['domain']} --repo {project['module']}",
            "   ```",
            "",
            "3. Create API scaffold",
            "",
            "   ```bash",
            f"   kubebuilder create api --group {api['group']} --version {api['version']} --kind {api['kind']} --resource {controller_flag}",
            "   ```",
            "",
            "4. Generate deepcopy code",
            "",
            "   ```bash",
            "   make generate",
            "   ```",
            "",
            "5. Generate manifests",
            "",
            "   ```bash",
            "   make manifests",
            "   ```",
            "",
            "6. Run tests",
            "",
            "   ```bash",
            "   make test",
            "   ```",
            "",
            "## Command Purpose",
            "",
            "- `mkdir -p`: Kubebuilder 프로젝트를 생성할 작업 디렉터리를 준비합니다.",
            "- `kubebuilder init`: Operator 프로젝트 기본 구조와 Go module을 생성합니다.",
            "- `kubebuilder create api`: CRD 타입과 Controller scaffold를 생성합니다.",
            "- `make generate`: `controller-gen`으로 deepcopy 코드를 생성합니다.",
            "- `make manifests`: CRD, RBAC, webhook 등 Kubernetes manifest를 생성합니다.",
            "- `make test`: Go test를 실행하여 기본 컴파일과 테스트 통과 여부를 확인합니다.",
            "",
            "## Preflight Checks",
            "",
            "- `go version`으로 Go 설치 여부와 버전을 확인합니다.",
            "- `kubebuilder version`으로 Kubebuilder 설치 여부를 확인합니다.",
            "- `make --version`으로 make 설치 여부를 확인합니다.",
            "- `controller-gen --version` 또는 `make generate` 경로로 controller-gen 사용 가능 여부를 확인합니다.",
            "- 현재 디렉터리가 저장소 루트인지 확인합니다.",
            f"- 동일 프로젝트 폴더 `{project['finalTargetDir']}`가 이미 존재하는지 확인합니다.",
            "",
            "## Expected Artifacts",
            "",
            f"- `api/{api['version']}/*_types.go`",
            "- `internal/controller/*_controller.go` 또는 `controllers/*_controller.go`",
            "- `config/crd`",
            "- `config/rbac`",
            "- `config/samples`",
            "- `Makefile`",
            "- `PROJECT`",
            "",
            "## Risks And Notes",
            "",
            "- 기존 디렉터리를 재사용하거나 강제로 삭제하면 사용자 변경사항이 사라질 수 있습니다.",
            "- `project.module` 값이 Go module 경로로 적절하지 않으면 `kubebuilder init` 또는 `go mod tidy` 단계에서 실패할 수 있습니다.",
            "- Kubebuilder가 설치한 `controller-gen` 버전과 현재 Go/Kubernetes 라이브러리 버전이 맞지 않으면 `make generate`가 실패할 수 있습니다.",
            "- Go module 초기화 중 네트워크 접근 또는 proxy 설정 문제로 의존성 다운로드가 실패할 수 있습니다.",
            "- `make test`는 envtest 바이너리 다운로드나 Kubernetes 테스트 환경 설정 문제의 영향을 받을 수 있습니다.",
            "",
            "## Validation Commands From Spec",
            "",
            *[f"- `{command}`" for command in model["validationCommands"]],
            "",
        ]
    )
    return "\n".join(lines)


def infer_project_name(kind: str) -> str:
    if not kind:
        return ""
    return f"{to_kebab(kind)}-operator"


def infer_domain(api_group: str, group: str) -> str:
    prefix = f"{group}."
    if api_group.startswith(prefix):
        return api_group[len(prefix) :]
    return ""


def to_kebab(value: str) -> str:
    result = []
    for index, char in enumerate(value):
        if index and char.isupper() and (value[index - 1].islower() or value[index - 1].isdigit()):
            result.append("-")
        result.append(char.lower())
    return "".join(result)


if __name__ == "__main__":
    raise SystemExit(main())
