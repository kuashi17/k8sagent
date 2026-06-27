"""Convert the generalized Operator spec into Controller generation IR."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.tools.controller_ir import (
    ControllerGenerationIR,
    FieldMapping,
    FieldMutability,
    ManagedResourceSpec,
    NameRule,
    RBACRule,
    ReconcileStrategy,
    ResourceCapability,
    StaticMutation,
    StatusMapping,
    UpdatePolicy,
)
from agent.tools.resource_catalog import (
    CatalogBehaviorPrimitive,
    ResourceCapabilityDefinition,
    load_resource_catalog,
)


def build_controller_ir(model: dict[str, Any]) -> ControllerGenerationIR:
    catalog = load_resource_catalog()
    resources_by_name = catalog.by_name()
    api = model["api"]
    fields = field_names(model.get("specFields") or [])
    status_fields = field_names(model.get("statusFields") or [])
    status_field_types = field_types(model.get("statusFields") or [])
    explicit_mappings = parse_explicit_mappings(
        (model.get("controller") or {}).get("fieldMappings") or []
    )
    resources = []
    seen = set()
    unsupported = []
    for raw_kind in (
        (model.get("controller") or {}).get("managedResources") or []
    ):
        defaults = resources_by_name.get(str(raw_kind))
        if not defaults:
            unsupported.append(str(raw_kind))
            continue
        if defaults.kind in seen:
            continue
        seen.add(defaults.kind)
        resources.append(
            build_managed_resource(
                defaults,
                fields,
                status_fields,
                status_field_types,
                explicit_mappings,
                catalog.primitives_by_name(),
            )
        )
    if unsupported:
        supported = ", ".join(
            sorted(item.kind for item in catalog.resources)
        )
        raise ValueError(
            "unsupported managed resources: "
            + ", ".join(unsupported)
            + f"; supported resources: {supported}"
        )
    return ControllerGenerationIR(
        project_module=str((model.get("project") or {}).get("module") or ""),
        api_group=str(api.get("group") or ""),
        api_version=str(api.get("version") or ""),
        kind=str(api.get("kind") or ""),
        spec_fields=sorted(fields),
        status_fields=sorted(status_fields),
        status_field_types=status_field_types,
        managed_resources=resources,
        rbac_rules=[
            RBACRule(
                api_group=str(item.get("apiGroup") or ""),
                resource=str(item.get("resource") or ""),
                verbs=[str(verb) for verb in item.get("verbs") or []],
            )
            for item in model.get("rbacResources") or []
            if item.get("resource")
        ],
    )


def build_managed_resource(
    defaults: ResourceCapabilityDefinition,
    fields: set[str],
    status_fields: set[str],
    status_field_types: dict[str, str],
    explicit_mappings: list[FieldMapping],
    primitives: dict[str, CatalogBehaviorPrimitive],
) -> ManagedResourceSpec:
    kind = defaults.kind
    name_field = first_field(fields, *defaults.nameFields)
    capabilities = capabilities_for(defaults)
    behavior_mappings, static_mutations, active_behaviors = (
        behavior_contract_for(defaults, primitives, fields)
    )
    mappings = mappings_for(
        defaults,
        fields,
        explicit_mappings,
        behavior_mappings,
    )
    return ManagedResourceSpec(
        resource_id=kind[:1].lower() + kind[1:],
        api_version=defaults.apiVersion,
        kind=kind,
        scope=defaults.scope,
        name=NameRule(
            source_path=f"spec.{name_field}" if name_field else "",
            fallback_template=f"{{metadata.name}}-{defaults.suffix}",
        ),
        strategy=defaults.strategy,
        capabilities=capabilities,
        ownership=defaults.ownership,
        deletion_policy=defaults.deletionPolicy,
        update_policy=resource_update_policy(defaults, mappings),
        watch=ResourceCapability.WATCH in capabilities,
        field_mappings=mappings,
        static_mutations=static_mutations,
        active_behaviors=active_behaviors,
        status_mappings=status_mappings_for(
            defaults,
            status_fields,
            status_field_types,
        ),
        disable_when=(
            f"spec.{defaults.disableField} == false"
            if defaults.disableField
            and defaults.disableField in fields
            else ""
        ),
        base_object=base_object_for(defaults, fields),
        label_paths=defaults.labelPaths,
        dependency_kind=defaults.dependencyKind,
        dependency_variable=defaults.dependencyVariable,
        dependency_target_path=defaults.dependencyTargetPath,
    )


def behavior_contract_for(
    defaults: ResourceCapabilityDefinition,
    primitives: dict[str, CatalogBehaviorPrimitive],
    fields: set[str],
) -> tuple[list[FieldMapping], list[StaticMutation], list[str]]:
    mappings: list[FieldMapping] = []
    static: list[StaticMutation] = []
    active: list[str] = []
    for binding in defaults.behaviorBindings:
        primitive = primitives[binding.primitive]
        present = [field in fields for field in primitive.activationFields]
        enabled = (
            all(present)
            if primitive.activationMode == "all"
            else any(present)
        )
        if not enabled:
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
    return mappings, static, active


def base_object_for(
    defaults: ResourceCapabilityDefinition,
    fields: set[str],
) -> dict[str, Any]:
    result = deepcopy(defaults.baseObject)
    for conditional in defaults.conditionalObjects:
        source = conditional.whenSource.removeprefix("spec.")
        if source in fields:
            merge_mapping(result, deepcopy(conditional.object))
    return result


def merge_mapping(
    target: dict[str, Any],
    source: dict[str, Any],
) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge_mapping(target[key], value)
        else:
            target[key] = value


def capabilities_for(
    defaults: ResourceCapabilityDefinition,
) -> list[ResourceCapability]:
    if defaults.strategy == ReconcileStrategy.READ_ONLY:
        return [
            ResourceCapability.WATCH,
            ResourceCapability.STATUS_SOURCE,
        ]
    if defaults.strategy == ReconcileStrategy.PATCH_EXISTING:
        return [
            ResourceCapability.UPDATE,
            ResourceCapability.WATCH,
            ResourceCapability.STATUS_SOURCE,
            ResourceCapability.PATCH_EXISTING,
        ]
    return [
        ResourceCapability.CREATE,
        ResourceCapability.UPDATE,
        ResourceCapability.WATCH,
        ResourceCapability.DELETE,
        ResourceCapability.STATUS_SOURCE,
    ]


def mappings_for(
    defaults: ResourceCapabilityDefinition,
    fields: set[str],
    explicit: list[FieldMapping],
    behavior_mappings: list[FieldMapping],
) -> list[FieldMapping]:
    kind = defaults.kind
    result = []
    for item in explicit:
        if target_resource(item.target_path) != kind:
            continue
        target = normalize_target_path(item.target_path)
        behavior = next(
            (
                candidate
                for candidate in behavior_mappings
                if candidate.source_path == item.source_path
                and candidate.target_path == target
            ),
            None,
        )
        catalog_mapping = next(
            (
                candidate
                for candidate in defaults.fieldMappings
                if f"spec.{candidate.source}" == item.source_path
                and candidate.target == target
            ),
            None,
        )
        result.append(
            item.model_copy(
                update={
                    "target_path": target,
                    "transform": (
                        behavior.transform
                        if behavior
                        else mapping_transform(defaults, item)
                    ),
                    "mutability": (
                        behavior.mutability
                        if behavior
                        else field_mutability(kind, target)
                    ),
                    "update_policy": (
                        behavior.update_policy
                        if behavior
                        else field_update_policy(kind, target)
                    ),
                    "assertion_path": (
                        catalog_mapping.assertionPath
                        if catalog_mapping
                        else ""
                    ),
                    "assertion_transform": (
                        catalog_mapping.assertionTransform
                        if catalog_mapping
                        else ""
                    ),
                }
            )
        )
    existing_pairs = {
        (item.source_path, item.target_path)
        for item in result
    }
    for item in defaults.fieldMappings:
        field = item.source
        target = item.target
        source = f"spec.{field}"
        if field in fields and (source, target) not in existing_pairs:
            result.append(
                FieldMapping(
                    source_path=source,
                    target_path=target,
                    transform=item.transform,
                    mutability=item.mutability,
                    update_policy=item.updatePolicy,
                    assertion_path=item.assertionPath,
                    assertion_transform=item.assertionTransform,
                )
            )
            existing_pairs.add((source, target))
    for mapping in behavior_mappings:
        pair = (mapping.source_path, mapping.target_path)
        if pair not in existing_pairs:
            result.append(mapping)
            existing_pairs.add(pair)
    return result


def mapping_transform(
    defaults: ResourceCapabilityDefinition,
    mapping: FieldMapping,
) -> str:
    target = normalize_target_path(mapping.target_path)
    source = mapping.source_path.removeprefix("spec.")
    contract = next(
        (
            item
            for item in defaults.fieldMappings
            if item.target == target and item.source == source
        ),
        next(
            (
                item
                for item in defaults.fieldMappings
                if item.target == target
            ),
            None,
        ),
    )
    return contract.transform if contract else mapping.transform


def normalize_target_path(path: str) -> str:
    prefix = path.split(".", 1)[0]
    if prefix not in load_resource_catalog().by_name():
        return path
    return path.split(".", 1)[1]


def field_mutability(
    kind: str,
    target: str,
) -> FieldMutability:
    definition = load_resource_catalog().by_name().get(kind)
    if definition:
        mapping = next(
            (
                item
                for item in definition.fieldMappings
                if item.target == target
            ),
            None,
        )
        if mapping:
            return mapping.mutability
    return FieldMutability.MUTABLE


def field_update_policy(kind: str, target: str) -> UpdatePolicy:
    if field_mutability(kind, target) == FieldMutability.IMMUTABLE:
        return UpdatePolicy.RECREATE
    return UpdatePolicy.IN_PLACE


def resource_update_policy(
    defaults: ResourceCapabilityDefinition,
    mappings: list[FieldMapping],
) -> UpdatePolicy:
    if defaults.strategy == ReconcileStrategy.READ_ONLY:
        return UpdatePolicy.NONE
    if any(
        item.update_policy == UpdatePolicy.RECREATE
        for item in mappings
    ):
        return UpdatePolicy.RECREATE
    return UpdatePolicy.IN_PLACE


def status_mappings_for(
    defaults: ResourceCapabilityDefinition,
    status_fields: set[str],
    status_field_types: dict[str, str],
) -> list[StatusMapping]:
    result = []
    for mapping in defaults.statusMappings:
        field = mapping.field
        if field not in status_fields:
            continue
        result.append(
            StatusMapping(
                source_path=mapping.source,
                target_path=f"status.{field}",
                transform=(
                    "resource-name"
                    if mapping.resourceName
                    else mapping.transform
                ),
                target_type=status_field_types.get(field, "string"),
            )
        )
    return result


def parse_explicit_mappings(
    values: list[Any],
) -> list[FieldMapping]:
    result = []
    for item in values:
        if not isinstance(item, dict):
            continue
        source = str(item.get("from") or "")
        target = str(item.get("to") or "")
        if source and target:
            result.append(
                FieldMapping(
                    source_path=source,
                    target_path=target,
                )
            )
    return result


def target_resource(path: str) -> str:
    prefix = path.split(".", 1)[0]
    definition = load_resource_catalog().by_name().get(prefix)
    return definition.kind if definition else prefix


def field_names(values: list[Any]) -> set[str]:
    return {
        str(item.get("name"))
        for item in values
        if isinstance(item, dict) and item.get("name")
    }


def field_types(values: list[Any]) -> dict[str, str]:
    return {
        str(item.get("name")): str(item.get("type") or "string")
        for item in values
        if isinstance(item, dict) and item.get("name")
    }


def first_field(fields: set[str], *candidates: str) -> str:
    return next((item for item in candidates if item in fields), "")
