"""Convert the generalized Operator spec into Controller generation IR."""

from __future__ import annotations

from typing import Any

from agent.tools.capability_adapter import adapt_capability
from agent.tools.capability_validation_policy import (
    validate_mutation_contract,
)

from agent.tools.controller_ir import (
    ControllerStateMachine,
    ControllerGenerationIR,
    DeletionPolicy,
    FieldMapping,
    FieldMutability,
    ManagedResourceSpec,
    NameRule,
    OwnershipPolicy,
    RBACRule,
    ReconcileStrategy,
    ResourceCapability,
    ResourceScope,
    StatusMapping,
    UpdatePolicy,
)
from agent.tools.resource_catalog import (
    CatalogBehaviorPrimitive,
    CatalogPrimitiveMutation,
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
    controller = model.get("controller") or {}
    policies = {
        str(item.get("kind")): item
        for item in controller.get("resourcePolicies") or []
        if isinstance(item, dict) and item.get("kind")
    }
    requested_resources = [
        *controller.get("managedResources", []),
        *controller.get("observedResources", []),
    ]
    resources = []
    seen = set()
    unsupported = []
    for raw_kind in requested_resources:
        defaults = resources_by_name.get(str(raw_kind))
        if not defaults:
            unsupported.append(str(raw_kind))
            continue
        if defaults.kind in seen:
            continue
        seen.add(defaults.kind)
        resource = build_managed_resource(
                defaults,
                fields,
                status_fields,
                status_field_types,
                explicit_mappings,
                catalog.primitives_by_name(),
            )
        resources.append(apply_resource_policy(resource, policies.get(str(raw_kind))))
    if unsupported:
        supported = ", ".join(
            sorted(item.kind for item in catalog.resources)
        )
        raise ValueError(
            "unsupported managed resources: "
            + ", ".join(unsupported)
            + f"; supported resources: {supported}"
        )
    finalizer_required = any(
        item.ownership == OwnershipPolicy.FINALIZER
        or item.deletion_policy == DeletionPolicy.EXPLICIT_DELETE
        for item in resources
    )
    api_group = str(api.get("group") or "")
    qualified_api_group = str(
        api.get("apiGroup")
        or (
            f"{api_group}.{api.get('domain')}"
            if api_group and api.get("domain")
            else api_group
        )
    )
    kind = str(api.get("kind") or "")
    return ControllerGenerationIR(
        project_module=str((model.get("project") or {}).get("module") or ""),
        api_group=api_group,
        api_version=str(api.get("version") or ""),
        kind=kind,
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
        state_machine=ControllerStateMachine(
            finalizer_name=(
                f"{qualified_api_group}/{kind.lower()}-finalizer"
                if finalizer_required
                else ""
            )
        ),
    )


def apply_resource_policy(
    resource: ManagedResourceSpec,
    policy: dict[str, Any] | None,
) -> ManagedResourceSpec:
    if not policy:
        return resource
    strategy = ReconcileStrategy(
        str(policy.get("strategy") or resource.strategy.value)
    )
    ownership = OwnershipPolicy(
        str(policy.get("ownership") or resource.ownership.value)
    )
    deletion = DeletionPolicy(
        str(
            policy.get("deletionPolicy")
            or resource.deletion_policy.value
        )
    )
    # Requirement parsers describe user intent, while the capability adapter
    # owns Kubernetes lifecycle constraints. A generic create-or-update policy
    # must not turn a safe patch-existing capability into a creator, and a
    # namespaced CR can never own a cluster-scoped object by ownerReference.
    if (
        resource.strategy == ReconcileStrategy.PATCH_EXISTING
        and strategy == ReconcileStrategy.CREATE_OR_UPDATE
    ):
        strategy = resource.strategy
    if (
        resource.scope == ResourceScope.CLUSTER
        and ownership == OwnershipPolicy.OWNER_REFERENCE
    ):
        ownership = resource.ownership
        deletion = resource.deletion_policy
    if strategy == ReconcileStrategy.READ_ONLY:
        return resource.model_copy(
            update={
                "strategy": strategy,
                "capabilities": [
                    ResourceCapability.WATCH,
                    ResourceCapability.STATUS_SOURCE,
                ],
                "ownership": OwnershipPolicy.NONE,
                "deletion_policy": DeletionPolicy.RETAIN,
                "update_policy": UpdatePolicy.NONE,
                "watch": True,
                "field_mappings": [],
                "static_mutations": [],
                "active_behaviors": [],
                "base_object": {},
                "label_paths": [],
                "dependency_kind": "",
                "dependency_variable": "",
                "dependency_target_path": "",
            }
        )
    return resource.model_copy(
        update={
            "strategy": strategy,
            "ownership": ownership,
            "deletion_policy": deletion,
        }
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
    catalog = load_resource_catalog()
    adapted = adapt_capability(
        defaults,
        primitives,
        fields,
        explicit_mappings,
        catalog.by_name(),
    )
    mappings = mappings_for(
        defaults,
        fields,
        explicit_mappings,
        adapted.field_mappings,
        primitives,
    )
    validate_mutation_contract(kind, mappings, adapted.static_mutations)
    return ManagedResourceSpec(
        resource_id=kind[:1].lower() + kind[1:],
        api_version=defaults.apiVersion,
        kind=kind,
        plural=defaults.plural,
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
        static_mutations=adapted.static_mutations,
        active_behaviors=adapted.active_behaviors,
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
        base_object=adapted.base_object,
        label_paths=defaults.labelPaths,
        dependency_kind=defaults.dependencyKind,
        dependency_variable=defaults.dependencyVariable,
        dependency_target_path=defaults.dependencyTargetPath,
    )


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
    primitives: dict[str, CatalogBehaviorPrimitive],
) -> list[FieldMapping]:
    kind = defaults.kind
    result = []
    explicit_pairs: set[tuple[str, str]] = set()
    for item in explicit:
        if target_resource(item.target_path) != kind:
            continue
        target = normalize_target_path(item.target_path)
        pair = (item.source_path, target)
        if pair in explicit_pairs:
            continue
        explicit_pairs.add(pair)
        primitive_mutation = behavior_mutation_for_target(
            defaults,
            primitives,
            target,
        )
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
        if primitive_mutation:
            transform = primitive_mutation.transform
            mutability = primitive_mutation.mutability
            update_policy = primitive_mutation.updatePolicy
        elif behavior:
            transform = behavior.transform
            mutability = behavior.mutability
            update_policy = behavior.update_policy
        else:
            transform = mapping_transform(defaults, item)
            mutability = field_mutability(kind, target)
            update_policy = field_update_policy(kind, target)
        result.append(
            item.model_copy(
                update={
                    "target_path": target,
                    "transform": transform,
                    "mutability": mutability,
                    "update_policy": update_policy,
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


def behavior_mutation_for_target(
    defaults: ResourceCapabilityDefinition,
    primitives: dict[str, CatalogBehaviorPrimitive],
    target: str,
) -> CatalogPrimitiveMutation | None:
    for binding in defaults.behaviorBindings:
        primitive = primitives[binding.primitive]
        for mutation in primitive.mutations:
            if mutation.target.format(**binding.paths) == target:
                return mutation
    return None


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
