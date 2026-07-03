"""Build generic kind lifecycle validation contracts from Controller IR."""

from __future__ import annotations

import base64
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent.tools.controller_ir import (
    ControllerGenerationIR,
    FieldMapping,
    FieldMutability,
    ManagedResourceSpec,
    ReconcileStrategy,
    UpdatePolicy,
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManagedResourceContract(ContractModel):
    resource: str
    name: str
    ownership: str
    deletionPolicy: str
    updatePolicy: str


class AssertionContract(ContractModel):
    resource: str
    name: str
    path: str
    equals: Any


class RBACCheckContract(ContractModel):
    verb: str
    resource: str
    apiGroup: str = ""
    expectedAllowed: bool = True


class ObservedResourceContract(ContractModel):
    resource: str
    name: str = ""
    labelSelector: dict[str, str] = Field(default_factory=dict)
    mutationPatch: dict[str, Any] = Field(default_factory=dict)
    statusPath: str = ""
    expectedStatus: Any = None
    statusSourcePath: str = ""
    deletionExpectation: str = "retain"


class StatusProjectionContract(ContractModel):
    resource: str
    name: str
    sourcePath: str
    statusPath: str


class KindValidationContract(ContractModel):
    resource: str
    sampleName: str
    managedResources: list[ManagedResourceContract]
    observedResources: list[ObservedResourceContract] = Field(
        default_factory=list
    )
    statusProjections: list[StatusProjectionContract] = Field(
        default_factory=list
    )
    initialAssertions: list[AssertionContract] = Field(
        default_factory=list
    )
    driftAssertions: list[AssertionContract] = Field(
        default_factory=list
    )
    updateSpec: dict[str, Any] = Field(default_factory=dict)
    updateAssertions: list[AssertionContract] = Field(
        default_factory=list
    )
    updateMode: str = UpdatePolicy.NONE.value
    immutableSpec: dict[str, Any] = Field(default_factory=dict)
    immutableAssertions: list[AssertionContract] = Field(
        default_factory=list
    )
    setupResources: list[dict[str, Any]] = Field(default_factory=list)
    rbacChecks: list[RBACCheckContract] = Field(default_factory=list)
    stateMachineStatus: bool = True
    finalizer: str = ""


def build_validation_contract(
    ir: ControllerGenerationIR,
    sample: dict[str, Any],
    custom_resource_plural: str,
    custom_resource_api_group: str,
) -> KindValidationContract:
    metadata = sample.get("metadata") or {}
    sample_name = str(metadata.get("name") or "")
    sample_spec = sample.get("spec") or {}
    managed = []
    observed = []
    setup = []
    status_projections = []
    update_spec: dict[str, Any] = {}
    assertions = []
    initial_assertions = []
    drift_assertions = []
    update_mode = UpdatePolicy.NONE
    immutable_spec: dict[str, Any] = {}
    immutable_assertions: list[AssertionContract] = []
    rbac = [
        RBACCheckContract(
            verb="update",
            resource=f"{custom_resource_plural}/status",
            apiGroup=custom_resource_api_group,
        )
    ]
    for resource in ir.managed_resources:
        if resource.strategy != ReconcileStrategy.READ_ONLY:
            continue
        token = resource_token(resource)
        name = managed_name(resource, sample_name, sample_spec)
        probe = external_watch_probe(resource, name)
        selector = observed_selector(resource, ir, sample_name, sample_spec)
        observed.append(
            ObservedResourceContract(
                resource=token,
                name="" if selector else name,
                labelSelector=selector,
                mutationPatch=probe.get("mutationPatch") or {},
                statusPath=str(probe.get("statusPath") or ""),
                expectedStatus=probe.get("expectedStatus"),
                statusSourcePath=str(probe.get("statusSourcePath") or ""),
                deletionExpectation=(
                    "transitive-delete" if selector else "retain"
                ),
            )
        )
        setup_resource = observed_setup_resource(resource, name)
        if setup_resource:
            setup.append(setup_resource)
        for verb in ("get", "list", "watch"):
            rbac.append(
                RBACCheckContract(
                    verb=verb,
                    resource=(resource.plural or pluralize(token)),
                    apiGroup=managed_api_group(resource),
                )
            )
        for verb in ("create", "update", "patch", "delete"):
            rbac.append(
                RBACCheckContract(
                    verb=verb,
                    resource=(resource.plural or pluralize(token)),
                    apiGroup=managed_api_group(resource),
                    expectedAllowed=False,
                )
            )
    for resource in ir.renderable_resources():
        token = resource_token(resource)
        name = managed_name(resource, sample_name, sample_spec)
        managed.append(
            ManagedResourceContract(
                resource=token,
                name=name,
                ownership=resource.ownership.value,
                deletionPolicy=resource.deletion_policy.value,
                updatePolicy=resource.update_policy.value,
            )
        )
        status_projections.extend(
            StatusProjectionContract(
                resource=token,
                name=name,
                sourcePath=(
                    "metadata.name"
                    if mapping.transform == "resource-name"
                    else mapping.source_path
                ),
                statusPath=mapping.target_path,
            )
            for mapping in resource.status_mappings
            if (
                mapping.transform == "resource-name"
                or (
                    mapping.source_path == "status.readyReplicas"
                    and resource.kind == "Deployment"
                    and len(ir.renderable_resources()) == 1
                )
            )
        )
        resource_assertions = initial_assertions_for(
            resource, sample_spec, name
        )
        initial_assertions.extend(resource_assertions)
        drift_assertions.extend(
            item
            for item in resource_assertions
            if is_safe_drift_path(item.path)
            and not (
                resource.kind == "Job"
                and item.path.startswith("spec.template.")
            )
        )
        if resource.strategy == ReconcileStrategy.PATCH_EXISTING:
            setup.append(
                {
                    "apiVersion": resource.api_version,
                    "kind": resource.kind,
                    "metadata": {"name": name},
                }
            )
        update = lifecycle_update(resource, sample_spec, name)
        if update and not update_spec:
            update_spec.update(update["spec"])
            assertions.extend(update["assertions"])
            update_mode = UpdatePolicy(update["mode"])
        immutable = immutable_lifecycle_update(
            resource,
            sample_spec,
            name,
        )
        if immutable and not immutable_spec:
            immutable_spec.update(immutable["spec"])
            immutable_assertions.extend(immutable["assertions"])
        rbac.append(
            RBACCheckContract(
                verb=(
                    "update"
                    if resource.strategy
                    == ReconcileStrategy.PATCH_EXISTING
                    else "create"
                ),
                resource=(resource.plural or pluralize(token)),
                apiGroup=managed_api_group(resource),
            )
        )
    return KindValidationContract(
        resource=ir.kind.lower(),
        sampleName=sample_name,
        managedResources=managed,
        observedResources=observed,
        statusProjections=status_projections,
        initialAssertions=initial_assertions,
        driftAssertions=drift_assertions[:1],
        updateSpec=update_spec,
        updateAssertions=assertions,
        updateMode=update_mode.value,
        immutableSpec=immutable_spec,
        immutableAssertions=immutable_assertions,
        setupResources=setup,
        rbacChecks=rbac,
        finalizer=ir.state_machine.finalizer_name,
    )


def external_watch_probe(
    resource: ManagedResourceSpec,
    name: str,
) -> dict[str, Any]:
    for mapping in resource.status_mappings:
        if mapping.transform == "resource-name":
            return {
                "statusPath": mapping.target_path,
                "statusSourcePath": "metadata.name",
            }
        if mapping.source_path == "spec.replicas":
            return {
                "mutationPatch": {"spec": {"replicas": 2}},
                "statusPath": mapping.target_path,
                "expectedStatus": 2,
            }
    return {}


def observed_selector(
    resource: ManagedResourceSpec,
    ir: ControllerGenerationIR,
    sample_name: str,
    sample_spec: dict[str, Any],
) -> dict[str, str]:
    if not resource.selector_label or not resource.selector_dependency_kind:
        return {}
    dependency = ir.resource(resource.selector_dependency_kind)
    if not dependency:
        return {}
    return {
        resource.selector_label: managed_name(
            dependency,
            sample_name,
            sample_spec,
        )
    }


def observed_setup_resource(
    resource: ManagedResourceSpec,
    name: str,
) -> dict[str, Any]:
    if resource.kind == "Deployment":
        labels = {"app": name}
        return {
            "apiVersion": resource.api_version,
            "kind": resource.kind,
            "metadata": {"name": name},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": labels},
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "containers": [
                            {
                                "name": "application",
                                "image": "nginx:alpine",
                            }
                        ]
                    },
                },
            },
        }
    return {}


def lifecycle_update(
    resource: ManagedResourceSpec,
    sample_spec: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    ordered = sorted(
        resource.field_mappings,
        key=lambda item: (
            item.transform != "env-map",
            item.mutability != FieldMutability.MUTABLE,
            item.target_path,
        ),
    )
    for mapping in ordered:
        if mapping.update_policy == UpdatePolicy.IMMUTABLE:
            continue
        candidate = update_candidate(mapping, sample_spec)
        if not candidate:
            continue
        field, updated, expected = candidate
        return {
            "spec": {field: updated},
            "mode": mapping.update_policy.value,
            "assertions": [
                AssertionContract(
                    resource=resource_token(resource),
                    name=name,
                    path=assertion_path(mapping),
                    equals=expected,
                )
            ],
        }
    return {}


def immutable_lifecycle_update(
    resource: ManagedResourceSpec,
    sample_spec: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    for mapping in resource.field_mappings:
        if mapping.update_policy != UpdatePolicy.IMMUTABLE:
            continue
        candidate = update_candidate(mapping, sample_spec)
        if not candidate:
            continue
        field, updated, _ = candidate
        current = sample_spec.get(field)
        return {
            "spec": {field: updated},
            "assertions": [
                AssertionContract(
                    resource=resource_token(resource),
                    name=name,
                    path=assertion_path(mapping),
                    equals=transformed_value(
                        mapping.assertion_transform or mapping.transform,
                        current,
                    ),
                )
            ],
        }
    return {}


def initial_assertions_for(
    resource: ManagedResourceSpec,
    sample_spec: dict[str, Any],
    name: str,
) -> list[AssertionContract]:
    assertions: list[AssertionContract] = []
    for mapping in resource.field_mappings:
        field = mapping.source_path.removeprefix("spec.")
        if field not in sample_spec:
            continue
        value = sample_spec[field]
        if mapping.transform == "merge-string-map":
            if isinstance(value, dict):
                assertions.extend(
                    AssertionContract(
                        resource=resource_token(resource),
                        name=name,
                        path=f"{mapping.target_path}.{key}",
                        equals=item,
                    )
                    for key, item in sorted(value.items())
                )
            continue
        assertions.append(
            AssertionContract(
                resource=resource_token(resource),
                name=name,
                path=(mapping.assertion_path or mapping.target_path),
                equals=transformed_value(
                    mapping.assertion_transform or mapping.transform,
                    value,
                ),
            )
        )
    assertions.extend(
        AssertionContract(
            resource=resource_token(resource),
            name=name,
            path=mutation.target_path,
            equals=mutation.value,
        )
        for mutation in resource.static_mutations
    )
    return assertions


def transformed_value(transform: str, value: Any) -> Any:
    if transform == "env-map" and isinstance(value, dict):
        return [
            {"name": key, "value": str(value[key])}
            for key in sorted(value)
        ]
    if transform == "base64-string-map" and isinstance(value, dict):
        return {
            str(key): base64.b64encode(str(item).encode("utf-8")).decode(
                "ascii"
            )
            for key, item in value.items()
        }
    return value


def is_safe_drift_path(path: str) -> bool:
    """Limit runtime drift mutation to fields accepted by Kubernetes APIs."""
    return any(
        marker in path
        for marker in (
            ".image",
            ".replicas",
            ".suspend",
            ".port",
            ".targetPort",
            "metadata.labels.",
        )
    ) or path in {"data", "stringData"}


def update_candidate(
    mapping: FieldMapping,
    sample_spec: dict[str, Any],
) -> tuple[str, Any, Any] | None:
    field = mapping.source_path.removeprefix("spec.")
    current = sample_spec.get(field)
    if (
        mapping.target_path == "spec.resources.requests.storage"
        and isinstance(current, str)
    ):
        match = re.fullmatch(r"(\d+)([A-Za-z]+)", current)
        if match:
            updated = f"{int(match.group(1)) + 1}{match.group(2)}"
            return field, updated, updated
    if mapping.transform == "env-map" and isinstance(current, dict):
        updated = {**current, "PROFILELESS_E2E": "updated"}
        expected = [
            {"name": key, "value": str(updated[key])}
            for key in sorted(updated)
        ]
        return field, updated, expected
    if mapping.target_path.endswith(".replicas") and isinstance(
        current,
        int,
    ):
        return field, current + 1, current + 1
    if mapping.transform == "int64" and isinstance(current, int):
        return field, current + 1, current + 1
    if mapping.target_path.endswith(".suspend") and isinstance(
        current,
        bool,
    ):
        return field, not current, not current
    if mapping.target_path == "metadata.labels" and isinstance(
        current,
        dict,
    ):
        updated = {**current, "profileless-e2e": "updated"}
        return (
            field,
            updated,
            "updated",
        )
    if (
        mapping.mutability == FieldMutability.IMMUTABLE
        and isinstance(current, str)
        and current
    ):
        updated = f"{current}-updated"
        return field, updated, updated
    if (
        mapping.mutability == FieldMutability.IMMUTABLE
        and isinstance(current, list)
        and current
    ):
        updated = [*current, "ReadOnlyMany"]
        return field, updated, updated
    return None


def assertion_path(mapping: FieldMapping) -> str:
    if mapping.assertion_path:
        return mapping.assertion_path
    if mapping.target_path == "metadata.labels":
        return "metadata.labels.profileless-e2e"
    return mapping.target_path


def managed_name(
    resource: ManagedResourceSpec,
    sample_name: str,
    sample_spec: dict[str, Any],
) -> str:
    source = resource.name.source_path
    if source.startswith("spec."):
        value = sample_spec.get(source.removeprefix("spec."))
        if value:
            return str(value)
    suffix = resource.name.fallback_template.replace(
        "{metadata.name}-",
        "",
    )
    return f"{sample_name}-{suffix}"


def resource_token(resource: ManagedResourceSpec) -> str:
    return resource.kind.lower()


def managed_api_group(resource: ManagedResourceSpec) -> str:
    if "/" not in resource.api_version:
        return ""
    return resource.api_version.split("/", 1)[0]


def pluralize(value: str) -> str:
    if value.endswith("s"):
        return value + "es"
    if value.endswith("y"):
        return value[:-1] + "ies"
    return value + "s"
