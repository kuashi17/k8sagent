"""Behavior-oriented intermediate representation for Controller generation."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class StatusMapping(IRModel):
    source_path: str
    target_path: str
    transform: str = "direct"
    target_type: str = "string"


class RBACRule(IRModel):
    api_group: str = ""
    resource: str
    verbs: list[str]


class ManagedResourceSpec(IRModel):
    resource_id: str
    api_version: str
    kind: str
    scope: ResourceScope
    name: NameRule
    strategy: ReconcileStrategy
    emitter: str
    capabilities: list[ResourceCapability]
    ownership: OwnershipPolicy
    deletion_policy: DeletionPolicy
    update_policy: UpdatePolicy = UpdatePolicy.IN_PLACE
    watch: bool
    field_mappings: list[FieldMapping] = Field(default_factory=list)
    status_mappings: list[StatusMapping] = Field(default_factory=list)
    disable_when: str = ""
    base_spec: dict[str, Any] = Field(default_factory=dict)
    label_paths: list[str] = Field(default_factory=list)
    dependency_kind: str = ""
    dependency_variable: str = ""


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
