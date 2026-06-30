"""Build generic kind lifecycle validation contracts from Controller IR."""

from __future__ import annotations

import base64
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
    name: str
    mutationPatch: dict[str, Any] = Field(default_factory=dict)
    statusPath: str = ""
    expectedStatus: Any = None


class KindValidationContract(ContractModel):
    resource: str
    sampleName: str
    managedResources: list[ManagedResourceContract]
    observedResources: list[ObservedResourceContract] = Field(
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
    update_spec: dict[str, Any] = {}
    assertions = []
    initial_assertions = []
    drift_assertions = []
    update_mode = UpdatePolicy.NONE
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
        observed.append(
            ObservedResourceContract(
                resource=token,
                name=name,
                mutationPatch=probe.get("mutationPatch") or {},
                statusPath=str(probe.get("statusPath") or ""),
                expectedStatus=probe.get("expectedStatus"),
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
                deletionPolicy=resource.deletion_policy.value,
                updatePolicy=resource.update_policy.value,
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
        initialAssertions=initial_assertions,
        driftAssertions=drift_assertions[:1],
        updateSpec=update_spec,
        updateAssertions=assertions,
        updateMode=update_mode.value,
        setupResources=setup,
        rbacChecks=rbac,
        finalizer=ir.state_machine.finalizer_name,
    )


def external_watch_probe(
    resource: ManagedResourceSpec,
    name: str,
) -> dict[str, Any]:
    for mapping in resource.status_mappings:
        if mapping.source_path == "spec.replicas":
            return {
                "mutationPatch": {"spec": {"replicas": 2}},
                "statusPath": mapping.target_path,
                "expectedStatus": 2,
            }
    return {}


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
