"""Adapt declarative capability catalog entries into generic IR fragments."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from agent.tools.controller_ir import FieldMapping, StaticMutation
from agent.tools.resource_catalog import (
    CatalogBehaviorPrimitive,
    ResourceCapabilityDefinition,
)


@dataclass(frozen=True)
class AdaptedCapability:
    field_mappings: list[FieldMapping]
    static_mutations: list[StaticMutation]
    active_behaviors: list[str]
    base_object: dict


def adapt_capability(
    definition: ResourceCapabilityDefinition,
    primitives: dict[str, CatalogBehaviorPrimitive],
    fields: set[str],
    explicit_mappings: list[FieldMapping],
    resource_names: dict[str, ResourceCapabilityDefinition],
) -> AdaptedCapability:
    """Resolve optional catalog bindings without leaking them into renderers."""
    mappings: list[FieldMapping] = []
    static: list[StaticMutation] = []
    active: list[str] = []
    explicit_targets = {
        normalize_target(mapping.target_path, resource_names)
        for mapping in explicit_mappings
        if target_resource(mapping.target_path, resource_names)
        == definition.kind
    }
    for binding in definition.behaviorBindings:
        primitive = primitives[binding.primitive]
        present = [field in fields for field in primitive.activationFields]
        enabled_by_field = (
            all(present)
            if primitive.activationMode == "all"
            else any(present)
        )
        rendered_targets = {
            mutation.target.format(**binding.paths)
            for mutation in primitive.mutations
        }
        if not enabled_by_field and not rendered_targets.intersection(
            explicit_targets
        ):
            continue
        active.append(primitive.name)
        for mutation in primitive.mutations:
            target = mutation.target.format(**binding.paths)
            if mutation.source and mutation.source in fields:
                mappings.append(
                    FieldMapping(
                        source_path=f"spec.{mutation.source}",
                        target_path=target,
                        transform=mutation.transform,
                        mutability=mutation.mutability,
                        update_policy=mutation.updatePolicy,
                    )
                )
            elif target in explicit_targets:
                continue
            elif mutation.source and mutation.defaultValue is not None:
                static.append(
                    StaticMutation(
                        target_path=target,
                        value=mutation.defaultValue,
                        transform=mutation.transform,
                    )
                )
            elif mutation.literal is not None:
                static.append(
                    StaticMutation(
                        target_path=target,
                        value=mutation.literal,
                        transform=mutation.transform,
                    )
                )

    base_object = deepcopy(definition.baseObject)
    for conditional in definition.conditionalObjects:
        source = conditional.whenSource.removeprefix("spec.")
        if source in fields:
            merge_mapping(base_object, deepcopy(conditional.object))
    return AdaptedCapability(
        field_mappings=mappings,
        static_mutations=static,
        active_behaviors=active,
        base_object=base_object,
    )


def normalize_target(
    path: str,
    resources: dict[str, ResourceCapabilityDefinition],
) -> str:
    prefix = path.split(".", 1)[0]
    if prefix not in resources or "." not in path:
        return path
    return path.split(".", 1)[1]


def target_resource(
    path: str,
    resources: dict[str, ResourceCapabilityDefinition],
) -> str:
    prefix = path.split(".", 1)[0]
    definition = resources.get(prefix)
    return definition.kind if definition else prefix


def merge_mapping(target: dict, source: dict) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_mapping(target[key], value)
        else:
            target[key] = value
