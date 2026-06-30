"""Behavior-oriented intermediate representation for Controller generation."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IRModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResourceScope(str, Enum):
    NAMESPACED = "Namespaced"
    CLUSTER = "Cluster"


class ReconcileStrategy(str, Enum):
    CREATE_OR_UPDATE = "create-or-update"
    PATCH_EXISTING = "patch-existing"
    READ_ONLY = "read-only"


class OwnershipPolicy(str, Enum):
    OWNER_REFERENCE = "ownerReference"
    FINALIZER = "finalizer"
    NONE = "none"


class DeletionPolicy(str, Enum):
    GARBAGE_COLLECT = "garbage-collect"
    EXPLICIT_DELETE = "explicit-delete"
    RETAIN = "retain"


class UpdatePolicy(str, Enum):
    IN_PLACE = "in-place"
    RECREATE = "recreate"
    IMMUTABLE = "immutable"
    NONE = "none"


class FieldMutability(str, Enum):
    MUTABLE = "mutable"
    IMMUTABLE = "immutable"


class ResourceCapability(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    WATCH = "watch"
    DELETE = "delete"
    STATUS_SOURCE = "status-source"
    PATCH_EXISTING = "patch-existing"


class NameRule(IRModel):
    source_path: str = ""
    fallback_template: str


class FieldMapping(IRModel):
    source_path: str
    target_path: str
    transform: str = "direct"
    mutability: FieldMutability = FieldMutability.MUTABLE
    update_policy: UpdatePolicy = UpdatePolicy.IN_PLACE
    assertion_path: str = ""
    assertion_transform: str = ""


class StaticMutation(IRModel):
    target_path: str
    value: Any
    transform: str = "direct"


class StatusMapping(IRModel):
    source_path: str
    target_path: str
    transform: str = "direct"
    target_type: str = "string"


class RBACRule(IRModel):
    api_group: str = ""
    resource: str
    verbs: list[str]


class ControllerStateMachine(IRModel):
    observed_generation: bool = True
    conditions: bool = True
    success_requeue_seconds: int = Field(default=30, ge=1)
    failure_requeue_seconds: int = Field(default=10, ge=1)
    recreation_requeue_seconds: int = Field(default=2, ge=1)
    finalizer_name: str = ""


class ManagedResourceSpec(IRModel):
    resource_id: str
    api_version: str
    kind: str
    plural: str = ""
    scope: ResourceScope
    name: NameRule
    strategy: ReconcileStrategy
    capabilities: list[ResourceCapability]
    ownership: OwnershipPolicy
    deletion_policy: DeletionPolicy
    update_policy: UpdatePolicy = UpdatePolicy.IN_PLACE
    watch: bool
    field_mappings: list[FieldMapping] = Field(default_factory=list)
    static_mutations: list[StaticMutation] = Field(default_factory=list)
    active_behaviors: list[str] = Field(default_factory=list)
    status_mappings: list[StatusMapping] = Field(default_factory=list)
    disable_when: str = ""
    base_object: dict[str, Any] = Field(default_factory=dict)
    label_paths: list[str] = Field(default_factory=list)
    dependency_kind: str = ""
    dependency_variable: str = ""
    dependency_target_path: str = ""

    @model_validator(mode="after")
    def validate_lifecycle_policy(self) -> "ManagedResourceSpec":
        if (
            self.scope == ResourceScope.CLUSTER
            and self.ownership == OwnershipPolicy.OWNER_REFERENCE
        ):
            raise ValueError(
                f"cluster-scoped resource {self.kind} cannot use ownerReference"
            )
        if self.strategy == ReconcileStrategy.PATCH_EXISTING and (
            self.ownership != OwnershipPolicy.NONE
            or self.deletion_policy != DeletionPolicy.RETAIN
        ):
            raise ValueError(
                f"patch-existing resource {self.kind} must be retained "
                "without ownership"
            )
        return self


class ControllerGenerationIR(IRModel):
    project_module: str
    api_group: str
    api_version: str
    kind: str
    spec_fields: list[str]
    status_fields: list[str]
    status_field_types: dict[str, str] = Field(default_factory=dict)
    managed_resources: list[ManagedResourceSpec]
    rbac_rules: list[RBACRule]
    state_machine: ControllerStateMachine = Field(
        default_factory=ControllerStateMachine
    )

    def resource(self, kind: str) -> ManagedResourceSpec | None:
        return next(
            (
                item
                for item in self.managed_resources
                if item.kind == kind
            ),
            None,
        )

    def renderable_resources(self) -> list[ManagedResourceSpec]:
        return [
            item
            for item in self.managed_resources
            if item.strategy != ReconcileStrategy.READ_ONLY
        ]

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
