#!/usr/bin/env python3
"""Generate a profile-less Operator and validate it in kind."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.evaluation.profile_kind_matrix import parse_summary
from agent.evaluation.kind_contract_builder import (
    build_validation_contract,
)
from agent.evaluation.profileless_compile_runner import (
    compile_requirement,
)
from agent.tools.artifact_patcher import normalize_spec
from agent.tools.controller_ir_builder import build_controller_ir


DEFAULT_MATRIX = (
    REPO_ROOT
    / "evaluation"
    / "fixtures"
    / "profileless-kind-matrix.yaml"
)

def main() -> int:
    started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--requirement",
        action="append",
        default=[],
        help="Run one requirement. Repeat to build a custom matrix.",
    )
    parser.add_argument(
        "--requirements",
        nargs="*",
        default=[],
        help="Requirement matrix used instead of the fixture file.",
    )
    parser.add_argument(
        "--matrix",
        default=str(DEFAULT_MATRIX),
        help="YAML fixture listing requirements for generalized E2E.",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--cluster-name",
        default="profileless-matrix",
    )
    parser.add_argument(
        "--precompiled-results",
        default="",
        help="Reuse profileless compile results and generated projects.",
    )
    args = parser.parse_args()

    configured = (
        args.requirement
        or args.requirements
        or load_matrix(resolve(args.matrix))
    )
    requirements = [
        resolve(value)
        for value in configured
    ]
    output_dir = resolve(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    precompiled = (
        load_precompiled_results(resolve(args.precompiled_results))
        if args.precompiled_results
        else {}
    )
    work_root = Path(
        tempfile.mkdtemp(prefix="k8sagent-profileless-kind-")
    )
    try:
        results = [
            run_requirement(
                requirement,
                output_dir / "cases" / requirement.stem,
                work_root,
                args.cluster_name,
                precompiled.get(relative(requirement)),
            )
            for requirement in requirements
        ]
        status = (
            "passed"
            if results and all(
                item.get("status") == "passed" for item in results
            )
            else "failed"
        )
        payload = {
            "createdAt": datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "status": status,
            "profileUsed": False,
            "results": results,
            "timings": aggregate_kind_timings(
                results,
                round(time.perf_counter() - started, 3),
            ),
        }
        write_result(output_dir, payload)
        print(
            json.dumps(
                {
                    "status": status,
                    "outputDir": relative(output_dir),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0 if status == "passed" else 1
    finally:
        shutil.rmtree(work_root, ignore_errors=True)


def run_requirement(
    requirement: Path,
    output_dir: Path,
    work_root: Path,
    cluster_name: str,
    precompiled_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    case_started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    compile_result = precompiled_result or compile_requirement(
        requirement,
        output_dir / "compile",
        work_root,
    )
    if not compile_result.get("passed"):
        return result_payload(
            "failed",
            requirement,
            compile_result,
            {},
            [],
            "profile-less compile failed",
            {
                "caseSeconds": round(
                    time.perf_counter() - case_started,
                    3,
                ),
                "contractBuildSeconds": 0.0,
                "runnerSeconds": 0.0,
                "deploymentStepSeconds": 0.0,
                "deploymentCategories": {},
            },
            compile_reused=precompiled_result is not None,
        )

    spec_path = Path(compile_result["specPath"])
    project_dir = Path(compile_result["projectDir"])
    contract_started = time.perf_counter()
    contract = build_kind_contract(
        read_yaml(spec_path),
        project_dir,
        cluster_name,
    )
    contract_seconds = round(
        time.perf_counter() - contract_started,
        3,
    )
    command = build_kind_command(contract)
    runner_started = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
    )
    runner_seconds = round(
        time.perf_counter() - runner_started,
        3,
    )
    deployment = parse_summary(completed.stdout)
    status = (
        "passed"
        if completed.returncode == 0
        and deployment.get("status") == "succeeded"
        else "failed"
    )
    payload = result_payload(
        status,
        requirement,
        compile_result,
        deployment,
        command,
        completed.stderr[-4000:],
        {
            "caseSeconds": round(
                time.perf_counter() - case_started,
                3,
            ),
            "contractBuildSeconds": contract_seconds,
            "runnerSeconds": runner_seconds,
            "deploymentStepSeconds": deployment_step_seconds(
                deployment
            ),
            "deploymentCategories": aggregate_deployment_categories(
                deployment
            ),
        },
        compile_reused=precompiled_result is not None,
    )
    write_result(output_dir, payload)
    return payload


def load_precompiled_results(path: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"failed to load precompiled profileless results: {path}"
        ) from exc
    if payload.get("status") != "passed":
        raise ValueError("precompiled profileless results did not pass")
    results = {
        str(item.get("requirement") or ""): item
        for item in payload.get("requirements") or []
        if isinstance(item, dict) and item.get("passed")
    }
    missing_paths = [
        item.get("projectDir")
        for item in results.values()
        if not Path(str(item.get("projectDir") or "")).is_dir()
    ]
    if missing_paths:
        raise ValueError(
            "precompiled project directories are unavailable: "
            + ", ".join(str(item) for item in missing_paths)
        )
    return results


def build_kind_contract(
    spec: dict[str, Any],
    project_dir: Path,
    cluster_name: str,
) -> dict[str, Any]:
    model = normalize_spec(spec, {}, None)
    ir = build_controller_ir(model)
    project_name = str((model.get("project") or {}).get("name") or "")
    api = model["api"]
    sample_path = (
        project_dir
        / "config"
        / "samples"
        / f"{api['group']}_{api['version']}_{api['kind'].lower()}.yaml"
    )
    sample = read_yaml(sample_path)
    validator_config = build_validation_contract(
        ir,
        sample,
        str(
            api.get("plural")
            or pluralize(api["kind"].lower())
        ),
        str(api["apiGroup"]),
    ).model_dump(mode="json")
    return {
        "project": str(project_dir),
        "clusterName": cluster_name,
        "image": (
            f"{project_name}:profileless-"
            f"{project_content_digest(project_dir)}"
        ),
        "sample": str(sample_path),
        "namespace": f"{project_name}-system",
        "deployment": f"{project_name}-controller-manager",
        "validatorConfig": validator_config,
    }


def project_content_digest(project_dir: Path) -> str:
    digest = hashlib.sha256()
    candidates = []
    for path in project_dir.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(project_dir)
        if path.name in {"Dockerfile", "go.mod", "go.sum"} or (
            relative_path.parts
            and relative_path.parts[0] in {"api", "cmd", "internal"}
            and path.suffix == ".go"
        ):
            candidates.append(path)
    for path in sorted(candidates):
        relative_path = path.relative_to(project_dir)
        digest.update(str(relative_path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def build_kind_command(contract: dict[str, Any]) -> list[str]:
    return [
        sys.executable,
        "agent/tools/kind_deployment_runner.py",
        "--project",
        contract["project"],
        "--cluster-name",
        contract["clusterName"],
        "--image",
        contract["image"],
        "--sample",
        contract["sample"],
        "--namespace",
        contract["namespace"],
        "--deployment",
        contract["deployment"],
        "--validator",
        "managed-resources",
        "--validator-config",
        json.dumps(
            contract["validatorConfig"],
            ensure_ascii=False,
        ),
        "--skip-prepare-controller",
        "--skip-prevalidation",
    ]


def pluralize(value: str) -> str:
    if value.endswith("s"):
        return value + "es"
    if value.endswith("y"):
        return value[:-1] + "ies"
    return value + "s"


def result_payload(
    status: str,
    requirement: Path,
    compile_result: dict[str, Any],
    deployment: dict[str, Any],
    command: list[str],
    error: str,
    timings: dict[str, Any],
    *,
    compile_reused: bool = False,
) -> dict[str, Any]:
    return {
        "createdAt": datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "status": status,
        "requirement": relative(requirement),
        "profileUsed": False,
        "compileReused": compile_reused,
        "compile": compile_result,
        "kindCommand": command,
        "deploymentSummary": deployment,
        "timings": timings,
        "error": error,
    }


def aggregate_kind_timings(
    results: list[dict[str, Any]],
    total_seconds: float,
) -> dict[str, Any]:
    categories: dict[str, float] = {}
    for result in results:
        for name, seconds in (
            (result.get("timings") or {})
            .get("deploymentCategories", {})
            .items()
        ):
            categories[name] = categories.get(name, 0) + float(seconds)
    return {
        "totalSeconds": total_seconds,
        "caseSeconds": round(
            sum(
                float((item.get("timings") or {}).get("caseSeconds") or 0)
                for item in results
            ),
            3,
        ),
        "contractBuildSeconds": round(
            sum(
                float(
                    (item.get("timings") or {}).get(
                        "contractBuildSeconds"
                    )
                    or 0
                )
                for item in results
            ),
            3,
        ),
        "runnerSeconds": round(
            sum(
                float((item.get("timings") or {}).get("runnerSeconds") or 0)
                for item in results
            ),
            3,
        ),
        "deploymentStepSeconds": round(
            sum(
                float(
                    (item.get("timings") or {}).get(
                        "deploymentStepSeconds"
                    )
                    or 0
                )
                for item in results
            ),
            3,
        ),
        "deploymentCategories": {
            name: round(seconds, 3)
            for name, seconds in sorted(categories.items())
        },
    }


def deployment_step_seconds(deployment: dict[str, Any]) -> float:
    return round(
        sum(
            float(item.get("elapsedSeconds") or 0)
            for item in deployment.get("steps") or []
        ),
        3,
    )


def aggregate_deployment_categories(
    deployment: dict[str, Any],
) -> dict[str, float]:
    totals: dict[str, float] = {}
    for step in deployment.get("steps") or []:
        category = deployment_step_category(str(step.get("name") or ""))
        totals[category] = totals.get(category, 0) + float(
            step.get("elapsedSeconds") or 0
        )
    return {
        name: round(seconds, 3)
        for name, seconds in sorted(totals.items())
    }


def deployment_step_category(name: str) -> str:
    if name.startswith("docker-build"):
        return "docker-build"
    if name == "kind-load-image":
        return "kind-image-load"
    if name.startswith("kind-") or name == "kubectl-context":
        return "kind-cluster"
    if name in {"make-install", "make-deploy"}:
        return "install-deploy"
    if name in {
        "kubectl-rollout-status",
        "kubectl-get-deployment",
    }:
        return "deployment-readiness"
    if name.startswith("kubectl-auth-can-i"):
        return "rbac-preflight"
    if name == "docker-info":
        return "docker-preflight"
    return "lifecycle-validation"


def write_result(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "profileless-kind-results.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def load_matrix(path: Path) -> list[str]:
    data = read_yaml(path)
    return [
        str(item)
        for item in data.get("requirements") or []
        if item
    ]


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
