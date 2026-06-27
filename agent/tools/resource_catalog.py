"""Load and validate the external managed-resource capability catalog."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.tools.controller_ir import (
    DeletionPolicy,
    FieldMutability,
    OwnershipPolicy,
    ReconcileStrategy,
    ResourceScope,
    UpdatePolicy,
)


CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "resource-capabilities.yaml"
)


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogFieldMapping(CatalogModel):
    source: str
    target: str
    transform: str = "direct"
    mutability: FieldMutability = FieldMutability.MUTABLE
    updatePolicy: UpdatePolicy = UpdatePolicy.IN_PLACE


class CatalogStatusMapping(CatalogModel):
    field: str
    source: str
    transform: str = "direct"
    resourceName: bool = False


class CatalogConditionalObject(CatalogModel):
    whenSource: str
    object: dict[str, Any]


class ResourceCapabilityDefinition(CatalogModel):
    kind: str
    aliases: list[str] = Field(default_factory=list)
    apiVersion: str
    suffix: str
    scope: ResourceScope = ResourceScope.NAMESPACED
    strategy: ReconcileStrategy = ReconcileStrategy.CREATE_OR_UPDATE
    ownership: OwnershipPolicy = OwnershipPolicy.OWNER_REFERENCE
    deletionPolicy: DeletionPolicy = DeletionPolicy.GARBAGE_COLLECT
    nameFields: list[str] = Field(default_factory=list)
    fieldMappings: list[CatalogFieldMapping] = Field(
        default_factory=list
    )
    statusMappings: list[CatalogStatusMapping] = Field(
        default_factory=list
    )
    disableField: str = ""
    baseObject: dict[str, Any] = Field(default_factory=dict)
    conditionalObjects: list[CatalogConditionalObject] = Field(
        default_factory=list
    )
    labelPaths: list[str] = Field(default_factory=list)
    dependencyKind: str = ""
    dependencyVariable: str = ""
    dependencyTargetPath: str = ""

    @model_validator(mode="after")
    def validate_behavior(self) -> "ResourceCapabilityDefinition":
        names = [self.kind, *self.aliases]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate kind or alias in {self.kind}")
        for mapping in self.fieldMappings:
            validate_path(mapping.target, f"{self.kind} field mapping")
            if mapping.transform not in ALLOWED_TRANSFORMS:
                raise ValueError(
                    f"unsupported transform for {self.kind}: "
                    f"{mapping.transform}"
                )
        pairs = [
            (mapping.source, mapping.target)
            for mapping in self.fieldMappings
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError(f"duplicate field mapping in {self.kind}")
        for path in self.labelPaths:
            validate_path(path, f"{self.kind} label path")
        for mapping in self.statusMappings:
            validate_path(
                mapping.source,
                f"{self.kind} status mapping",
            )
        for conditional in self.conditionalObjects:
            validate_path(
                conditional.whenSource,
                f"{self.kind} conditional source",
            )
        if {"apiVersion", "kind"}.intersection(self.baseObject):
            raise ValueError(
                f"base object for {self.kind} cannot override identity"
            )
        metadata = self.baseObject.get("metadata") or {}
        if isinstance(metadata, dict) and {
            "name",
            "namespace",
            "ownerReferences",
        }.intersection(metadata):
            raise ValueError(
                f"base object for {self.kind} cannot override metadata identity"
            )
        dependency_values = (
            self.dependencyKind,
            self.dependencyVariable,
            self.dependencyTargetPath,
        )
        if any(dependency_values) and not all(dependency_values):
            raise ValueError(
                f"incomplete dependency contract for {self.kind}"
            )
        if self.dependencyTargetPath:
            validate_path(
                self.dependencyTargetPath,
                f"{self.kind} dependency target",
            )
        if self.strategy == ReconcileStrategy.READ_ONLY and (
            self.fieldMappings
            or self.baseObject
            or self.conditionalObjects
            or self.labelPaths
            or any(dependency_values)
        ):
            raise ValueError(
                f"read-only resource {self.kind} cannot declare mutations"
            )
        if (
            self.strategy == ReconcileStrategy.PATCH_EXISTING
            and (
                self.ownership != OwnershipPolicy.NONE
                or self.deletionPolicy != DeletionPolicy.RETAIN
            )
        ):
            raise ValueError(
                f"patch-existing resource {self.kind} must be retained "
                "without ownership"
            )
        if (
            self.scope == ResourceScope.CLUSTER
            and self.ownership == OwnershipPolicy.OWNER_REFERENCE
        ):
            raise ValueError(
                f"cluster-scoped resource {self.kind} cannot use ownerReference"
            )
        return self


class ResourceCapabilityCatalog(CatalogModel):
    version: int = Field(ge=1)
    resources: list[ResourceCapabilityDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> "ResourceCapabilityCatalog":
        names: dict[str, str] = {}
        canonical = {resource.kind for resource in self.resources}
        for resource in self.resources:
            for value in [resource.kind, *resource.aliases]:
                if value in names:
                    raise ValueError(
                        f"resource name {value} is shared by "
                        f"{names[value]} and {resource.kind}"
                    )
                names[value] = resource.kind
            if (
                resource.dependencyKind
                and resource.dependencyKind not in canonical
            ):
                raise ValueError(
                    f"unknown dependency {resource.dependencyKind} "
                    f"for {resource.kind}"
                )
        return self

    def by_name(self) -> dict[str, ResourceCapabilityDefinition]:
        result = {}
        for resource in self.resources:
            for value in [resource.kind, *resource.aliases]:
                result[value] = resource
        return result


@lru_cache(maxsize=1)
def load_resource_catalog(
    path: Path = CATALOG_PATH,
) -> ResourceCapabilityCatalog:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(
            f"failed to load resource capability catalog: {path}"
        ) from exc
    return ResourceCapabilityCatalog.model_validate(data)


ALLOWED_TRANSFORMS = {
    "direct",
    "int64",
    "string-map",
    "merge-string-map",
    "string-slice",
}


def validate_path(path: str, context: str) -> None:
    import re

    if not path or any(
        not re.fullmatch(r"[^.\[\]]+(?:\[\d+\])?", part)
        for part in path.split(".")
    ):
        raise ValueError(f"invalid nested path for {context}: {path}")
