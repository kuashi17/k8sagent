"""Validate proposed managed-resource capabilities against Kubernetes Discovery."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.tools.controller_ir import ReconcileStrategy, ResourceScope
from agent.tools.resource_catalog import ResourceCapabilityDefinition


class DiscoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CapabilityDiscoveryResult(DiscoveryModel):
    status: str = "passed"
    kind: str
    apiVersion: str
    endpoint: str
    resource: str
    scope: str
    supportedVerbs: list[str] = Field(default_factory=list)
    requiredVerbs: list[str] = Field(default_factory=list)
    rbacApiGroup: str = ""
    rbacResource: str
    rbacVerbs: list[str] = Field(default_factory=list)


DiscoveryReader = Callable[[str], dict[str, Any]]


def validate_capability_discovery(
    capability: ResourceCapabilityDefinition,
    reader: DiscoveryReader | None = None,
) -> CapabilityDiscoveryResult:
    endpoint = discovery_endpoint(capability.apiVersion)
    payload = (reader or kubectl_discovery)(endpoint)
    group_version = str(payload.get("groupVersion") or "")
    if group_version != capability.apiVersion:
        raise ValueError(
            "Kubernetes Discovery apiVersion mismatch for "
            f"{capability.kind}: expected={capability.apiVersion}, "
            f"actual={group_version or '<empty>'}"
        )
    candidates = [
        item
        for item in payload.get("resources") or []
        if isinstance(item, dict)
        and item.get("kind") == capability.kind
        and "/" not in str(item.get("name") or "")
    ]
    if len(candidates) != 1:
        raise ValueError(
            "Kubernetes Discovery did not find one canonical resource for "
            f"{capability.apiVersion}/{capability.kind}"
        )
    resource = candidates[0]
    discovered_plural = str(resource.get("name") or "")
    if capability.plural and capability.plural != discovered_plural:
        raise ValueError(
            f"Kubernetes Discovery plural mismatch for {capability.kind}: "
            f"expected={capability.plural}, actual={discovered_plural}"
        )
    expected_namespaced = capability.scope == ResourceScope.NAMESPACED
    actual_namespaced = bool(resource.get("namespaced"))
    if expected_namespaced != actual_namespaced:
        actual_scope = (
            ResourceScope.NAMESPACED.value
            if actual_namespaced
            else ResourceScope.CLUSTER.value
        )
        raise ValueError(
            f"Kubernetes Discovery scope mismatch for {capability.kind}: "
            f"expected={capability.scope.value}, actual={actual_scope}"
        )
    supported = sorted(str(item) for item in resource.get("verbs") or [])
    required = required_verbs(capability.strategy)
    missing = sorted(set(required) - set(supported))
    if missing:
        raise ValueError(
            f"Kubernetes API does not support required verbs for "
            f"{capability.kind}: {', '.join(missing)}"
        )
    capability.plural = discovered_plural
    rbac_group = (
        capability.apiVersion.split("/", 1)[0]
        if "/" in capability.apiVersion
        else ""
    )
    return CapabilityDiscoveryResult(
        kind=capability.kind,
        apiVersion=capability.apiVersion,
        endpoint=endpoint,
        resource=discovered_plural,
        scope=capability.scope.value,
        supportedVerbs=supported,
        requiredVerbs=required,
        rbacApiGroup=rbac_group,
        rbacResource=discovered_plural,
        rbacVerbs=required,
    )


def validate_proposal_discovery(
    capabilities: list[ResourceCapabilityDefinition],
    reader: DiscoveryReader | None = None,
) -> list[CapabilityDiscoveryResult]:
    return [
        validate_capability_discovery(capability, reader)
        for capability in capabilities
    ]


def discovery_endpoint(api_version: str) -> str:
    if "/" not in api_version:
        return f"/api/{api_version}"
    group, version = api_version.split("/", 1)
    return f"/apis/{group}/{version}"


def required_verbs(strategy: ReconcileStrategy) -> list[str]:
    if strategy == ReconcileStrategy.READ_ONLY:
        return ["get", "list", "watch"]
    if strategy == ReconcileStrategy.PATCH_EXISTING:
        return ["get", "list", "watch", "update", "patch"]
    return ["get", "list", "watch", "create", "update", "patch", "delete"]


def kubectl_discovery(endpoint: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["kubectl", "get", "--raw", endpoint],
            text=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"Kubernetes Discovery unavailable: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ValueError(
            f"Kubernetes Discovery unavailable for {endpoint}: {detail}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Kubernetes Discovery returned invalid JSON for {endpoint}"
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError("Kubernetes Discovery response must be an object")
    return payload
