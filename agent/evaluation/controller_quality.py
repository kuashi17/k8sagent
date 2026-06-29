"""Evaluate generated Controller artifacts against common quality criteria."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


CRITERIA = (
    "crdAccuracy",
    "rbacAccuracy",
    "reconcileBehavior",
    "statusUpdate",
    "idempotency",
    "deletionBehavior",
    "testsPassed",
)


def evaluate_controller_quality(
    project_dir: Path,
    spec_path: Path,
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not project_dir.is_dir():
        return {
            "status": "not-run",
            "projectDir": str(project_dir),
            "criteria": {
                name: criterion(False, "Generated project does not exist.")
                for name in CRITERIA
            },
            "score": 0,
        }

    spec = read_yaml(spec_path)
    api = spec.get("api") or {}
    kind = str(api.get("kind") or "")
    version = str(api.get("version") or "")
    controller_path = (
        project_dir
        / "internal"
        / "controller"
        / f"{kind.lower()}_controller.go"
    )
    controller = read_text(controller_path)
    requirement_text = read_requirement_text(spec)
    policies = (
        (spec.get("controller") or {}).get("resourcePolicies") or []
    )
    read_only_only = bool(policies) and all(
        item.get("strategy") == "read-only"
        for item in policies
        if isinstance(item, dict)
    )
    retains_resources = any(
        item.get("deletionPolicy") == "retain"
        for item in policies
        if isinstance(item, dict)
    )
    crd = first_yaml(project_dir / "config" / "crd" / "bases")
    role = first_yaml(project_dir / "config" / "rbac", "role.yaml")

    criteria = {
        "crdAccuracy": evaluate_crd(crd, spec),
        "rbacAccuracy": evaluate_rbac(role, spec),
        "reconcileBehavior": evaluate_reconcile(
            controller,
            kind,
            read_only=read_only_only,
        ),
        "statusUpdate": criterion(
            "Status().Update" in controller
            or "Status().Patch" in controller,
            "Controller updates the Custom Resource status subresource.",
        ),
        "idempotency": criterion(
            (read_only_only and bool(re.search(r"\br\.Get\(", controller)))
            or "CreateOrUpdate" in controller
            or (
                bool(re.search(r"\br\.Get\(", controller))
                and (
                    bool(re.search(r"\br\.Update\(", controller))
                    or bool(re.search(r"\br\.Patch\(", controller))
                )
            ),
            "Controller uses CreateOrUpdate or a Get-before-Update pattern.",
        ),
        "deletionBehavior": criterion(
            retains_resources
            or "삭제하지 않는다" in requirement_text
            or any(
                marker in controller
                for marker in (
                    "SetControllerReference",
                    "SetOwnerReference",
                    "Finalizer",
                    "finalizer",
                    "DeletionTimestamp",
                )
            ),
            (
                "Requirement explicitly preserves the observed or managed resource on deletion."
                if retains_resources or "삭제하지 않는다" in requirement_text
                else "Controller declares owner-reference or finalizer deletion behavior."
            ),
        ),
        "testsPassed": evaluate_tests(tool_results or []),
    }
    passed = sum(1 for item in criteria.values() if item["passed"])
    return {
        "status": "passed" if passed == len(criteria) else "failed",
        "projectDir": str(project_dir),
        "specPath": str(spec_path),
        "controllerPath": str(controller_path),
        "apiVersion": version,
        "kind": kind,
        "criteria": criteria,
        "behaviorEvidence": collect_behavior_evidence(controller, spec),
        "score": round(passed / len(criteria) * 100, 1),
    }


def evaluate_crd(crd: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    api = spec.get("api") or {}
    expected_kind = api.get("kind")
    expected_fields = {
        item.get("name")
        for item in spec.get("specFields") or []
        if isinstance(item, dict) and item.get("name")
    }
    versions = ((crd.get("spec") or {}).get("versions") or [])
    version = versions[0] if versions else {}
    schema = (
        ((version.get("schema") or {}).get("openAPIV3Schema") or {})
        .get("properties", {})
        .get("spec", {})
        .get("properties", {})
    )
    actual_fields = set(schema)
    status_enabled = bool(
        ((version.get("subresources") or {}).get("status")) == {}
        or "status" in (version.get("subresources") or {})
    )
    passed = (
        crd.get("kind") == "CustomResourceDefinition"
        and ((crd.get("spec") or {}).get("names") or {}).get("kind")
        == expected_kind
        and expected_fields.issubset(actual_fields)
        and status_enabled
    )
    return criterion(
        passed,
        "CRD kind, spec fields, and status subresource match the Operator spec.",
        expectedFields=sorted(expected_fields),
        actualFields=sorted(actual_fields),
        statusSubresource=status_enabled,
    )


def evaluate_rbac(role: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    expected = {
        (str(item.get("apiGroup") or ""), str(item.get("resource") or ""))
        for item in (spec.get("rbac") or {}).get("resources") or []
        if isinstance(item, dict) and item.get("resource")
    }
    actual: set[tuple[str, str]] = set()
    for rule in role.get("rules") or []:
        groups = rule.get("apiGroups") or [""]
        for group in groups:
            for resource in rule.get("resources") or []:
                actual.add((str(group), str(resource)))
    missing = sorted(expected - actual)
    return criterion(
        not missing and bool(expected),
        "Generated Role contains every resource inferred from the requirement.",
        expected=[f"{group or 'core'}/{resource}" for group, resource in sorted(expected)],
        missing=[f"{group or 'core'}/{resource}" for group, resource in missing],
    )


def evaluate_reconcile(
    controller: str,
    kind: str,
    *,
    read_only: bool = False,
) -> dict[str, Any]:
    has_reconcile = bool(
        re.search(
            rf"func \(r \*{re.escape(kind)}Reconciler\) Reconcile\(",
            controller,
        )
    )
    has_behavior = any(
        marker in controller
        for marker in (
            "CreateOrUpdate",
            "r.Create(",
            "r.Update(",
            "r.Patch(",
        )
    )
    if read_only:
        has_behavior = bool(re.search(r"\br\.Get\(", controller))
    placeholder = "TODO(user): Modify the Reconcile function" in controller
    return criterion(
        has_reconcile and has_behavior and not placeholder,
        "Reconcile contains concrete resource behavior instead of scaffold TODO code.",
    )


def evaluate_tests(tool_results: list[dict[str, Any]]) -> dict[str, Any]:
    for result in tool_results:
        if result.get("tool") != "validation":
            continue
        for step in result.get("steps") or []:
            if step.get("target") == "test":
                return criterion(
                    step.get("exitCode") == 0,
                    "make test completed successfully.",
                )
    return criterion(False, "No successful make test evidence was recorded.")


def collect_behavior_evidence(
    controller: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    managed = [
        str(item)
        for item in (spec.get("controller") or {}).get(
            "managedResources",
            [],
        )
        if item
    ]
    observed = [
        str(item)
        for item in (spec.get("controller") or {}).get(
            "observedResources",
            [],
        )
        if item
    ]
    watched = [
        item
        for item in managed
        if re.search(
            rf"(?:\.|\b)Owns\([^)]*{re.escape(item)}",
            controller,
        )
        or re.search(
            rf"(?:\.|\b)Owns\(&[A-Za-z0-9_.]*{re.escape(item)}\{{",
            controller,
        )
    ]
    status_fields = [
        str(item.get("name"))
        for item in spec.get("statusFields") or []
        if isinstance(item, dict) and item.get("name")
    ]
    assigned_status = [
        field
        for field in status_fields
        if re.search(
            rf"\.Status\.{re.escape(go_name(field))}\s*=",
            controller,
        )
    ]
    return {
        "managedResources": managed,
        "observedResources": observed,
        "watchRegistrations": watched,
        "statusFields": status_fields,
        "assignedStatusFields": assigned_status,
    }


def go_name(value: str) -> str:
    return value[:1].upper() + value[1:]


def criterion(passed: bool, evidence: str, **details: Any) -> dict[str, Any]:
    return {"passed": bool(passed), "evidence": evidence, **details}


def first_yaml(root: Path, filename: str = "") -> dict[str, Any]:
    if filename:
        path = root / filename
        return read_yaml(path)
    paths = sorted(root.glob("*.yaml")) if root.is_dir() else []
    return read_yaml(paths[0]) if paths else {}


def read_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def read_requirement_text(spec: dict[str, Any]) -> str:
    source = str((spec.get("metadata") or {}).get("sourceFile") or "")
    return read_text(Path(source)) if source else ""
