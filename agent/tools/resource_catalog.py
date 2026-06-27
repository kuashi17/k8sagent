"""Load and validate the external managed-resource capability catalog."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

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


class ResourceCapabilityDefinition(CatalogModel):
    kind: str
    aliases: list[str] = Field(default_factory=list)
    apiVersion: str
    suffix: str
    emitter: str
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
    baseSpec: dict[str, Any] = Field(default_factory=dict)
    labelPaths: list[str] = Field(default_factory=list)
    dependencyKind: str = ""
    dependencyVariable: str = ""


class ResourceCapabilityCatalog(CatalogModel):
    version: int
    resources: list[ResourceCapabilityDefinition]

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
