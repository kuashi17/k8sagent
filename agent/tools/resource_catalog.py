"""Load and validate the external managed-resource capability catalog."""

from __future__ import annotations

from functools import lru_cache
from string import Formatter
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
    assertionPath: str = ""
    assertionTransform: str = ""


class CatalogStatusMapping(CatalogModel):
    field: str
    source: str
    transform: str = "direct"
    resourceName: bool = False


class CatalogConditionalObject(CatalogModel):
    whenSource: str
    object: dict[str, Any]


class CatalogPrimitiveMutation(CatalogModel):
    target: str
    source: str = ""
    transform: str = "direct"
    literal: Any = None
    defaultValue: Any = None
    mutability: FieldMutability = FieldMutability.MUTABLE
    updatePolicy: UpdatePolicy = UpdatePolicy.IN_PLACE

    @model_validator(mode="after")
    def validate_value_source(self) -> "CatalogPrimitiveMutation":
        if not self.source and self.literal is None:
            raise ValueError(
                f"primitive mutation {self.target} requires source or literal"
            )
        if self.source and self.literal is not None:
            raise ValueError(
                f"primitive mutation {self.target} cannot mix source and literal"
            )
        if self.transform not in ALLOWED_TRANSFORMS:
            raise ValueError(
                f"unsupported primitive transform: {self.transform}"
            )
        return self


class CatalogBehaviorPrimitive(CatalogModel):
    name: str
    activationFields: list[str] = Field(min_length=1)
    activationMode: str = "any"
    mutations: list[CatalogPrimitiveMutation] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_activation(self) -> "CatalogBehaviorPrimitive":
        if self.activationMode not in {"any", "all"}:
            raise ValueError(
                f"unsupported activation mode for {self.name}: "
                f"{self.activationMode}"
            )
        if len(self.activationFields) != len(set(self.activationFields)):
            raise ValueError(
                f"activation fields for {self.name} must be unique"
            )
        pairs = [
            (mutation.source, mutation.target)
            for mutation in self.mutations
        ]
        if len(pairs) != len(set(pairs)):
            raise ValueError(
                f"primitive mutations for {self.name} must be unique"
            )
        for mutation in self.mutations:
            try:
                placeholders = {
                    field_name
                    for _, field_name, _, _ in Formatter().parse(
                        mutation.target
                    )
                    if field_name
                }
                rendered = mutation.target.format(
                    **{name: "root" for name in placeholders}
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(
                    f"invalid target template for {self.name}: "
                    f"{mutation.target}"
                ) from exc
            validate_path(rendered, f"{self.name} target template")
        return self


class CatalogBehaviorBinding(CatalogModel):
    primitive: str
    paths: dict[str, str] = Field(default_factory=dict)


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
    behaviorBindings: list[CatalogBehaviorBinding] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_behavior(self) -> "ResourceCapabilityDefinition":
        names = [self.kind, *self.aliases]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate kind or alias in {self.kind}")
        bindings = [
            binding.primitive for binding in self.behaviorBindings
        ]
        if len(bindings) != len(set(bindings)):
            raise ValueError(
                f"duplicate behavior binding in {self.kind}"
            )
        for mapping in self.fieldMappings:
            validate_path(mapping.target, f"{self.kind} field mapping")
            if mapping.transform not in ALLOWED_TRANSFORMS:
                raise ValueError(
                    f"unsupported transform for {self.kind}: "
                    f"{mapping.transform}"
                )
            if mapping.assertionPath:
                validate_path(
                    mapping.assertionPath,
                    f"{self.kind} assertion path",
                )
            if (
                mapping.assertionTransform
                and mapping.assertionTransform
                not in ALLOWED_ASSERTION_TRANSFORMS
            ):
                raise ValueError(
                    f"unsupported assertion transform for {self.kind}: "
                    f"{mapping.assertionTransform}"
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
            or self.behaviorBindings
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
    behaviorPrimitives: list[CatalogBehaviorPrimitive] = Field(
        default_factory=list
    )
    resources: list[ResourceCapabilityDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> "ResourceCapabilityCatalog":
        names: dict[str, str] = {}
        primitive_names = [
            primitive.name for primitive in self.behaviorPrimitives
        ]
        if len(primitive_names) != len(set(primitive_names)):
            raise ValueError("behavior primitive names must be unique")
        primitives = {
            primitive.name: primitive
            for primitive in self.behaviorPrimitives
        }
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
            for binding in resource.behaviorBindings:
                primitive = primitives.get(binding.primitive)
                if not primitive:
                    raise ValueError(
                        f"unknown behavior primitive {binding.primitive} "
                        f"for {resource.kind}"
                    )
                for path in binding.paths.values():
                    validate_path(
                        path,
                        f"{resource.kind} behavior binding",
                    )
                for mutation in primitive.mutations:
                    placeholders = {
                        field_name
                        for _, field_name, _, _ in Formatter().parse(
                            mutation.target
                        )
                        if field_name
                    }
                    missing = placeholders.difference(binding.paths)
                    if missing:
                        raise ValueError(
                            f"behavior {primitive.name} for {resource.kind} "
                            f"is missing paths: {', '.join(sorted(missing))}"
                        )
                    validate_path(
                        mutation.target.format(**binding.paths),
                        f"{resource.kind} behavior mutation",
                    )
        return self

    def by_name(self) -> dict[str, ResourceCapabilityDefinition]:
        result = {}
        for resource in self.resources:
            for value in [resource.kind, *resource.aliases]:
                result[value] = resource
        return result

    def primitives_by_name(self) -> dict[str, CatalogBehaviorPrimitive]:
        return {
            primitive.name: primitive
            for primitive in self.behaviorPrimitives
        }


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
    "env-map",
    "string-map",
    "merge-string-map",
    "string-slice",
}

ALLOWED_ASSERTION_TRANSFORMS = {
    "base64-string-map",
}


def validate_path(path: str, context: str) -> None:
    import re

    if not path or any(
        not re.fullmatch(r"[^.\[\]]+(?:\[\d+\])?", part)
        for part in path.split(".")
    ):
        raise ValueError(f"invalid nested path for {context}: {path}")
