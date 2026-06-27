"""Build generic kind lifecycle validation contracts from Controller IR."""

from __future__ import annotations

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


class KindValidationContract(ContractModel):
    resource: str
    sampleName: str
    managedResources: list[ManagedResourceContract]
    updateSpec: dict[str, Any] = Field(default_factory=dict)
    updateAssertions: list[AssertionContract] = Field(
        default_factory=list
    )
    updateMode: str = UpdatePolicy.NONE.value
    setupResources: list[dict[str, Any]] = Field(default_factory=list)
    rbacChecks: list[RBACCheckContract] = Field(default_factory=list)


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
    setup = []
    update_spec: dict[str, Any] = {}
    assertions = []
    update_mode = UpdatePolicy.NONE
    rbac = [
        RBACCheckContract(
            verb="update",
            resource=f"{custom_resource_plural}/status",
            apiGroup=custom_resource_api_group,
        )
    ]
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
                resource=pluralize(token),
                apiGroup=managed_api_group(resource),
            )
        )
    return KindValidationContract(
        resource=ir.kind.lower(),
        sampleName=sample_name,
        managedResources=managed,
        updateSpec=update_spec,
        updateAssertions=assertions,
        updateMode=update_mode.value,
        setupResources=setup,
        rbacChecks=rbac,
    )


def lifecycle_update(
    resource: ManagedResourceSpec,
    sample_spec: dict[str, Any],
    name: str,
) -> dict[str, Any]:
    ordered = sorted(
        resource.field_mappings,
        key=lambda item: (
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


def update_candidate(
    mapping: FieldMapping,
    sample_spec: dict[str, Any],
) -> tuple[str, Any, Any] | None:
    field = mapping.source_path.removeprefix("spec.")
    current = sample_spec.get(field)
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
