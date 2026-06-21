"""Convert the generalized Operator spec into Controller generation IR."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.tools.controller_ir import (
    ControllerGenerationIR,
    DeletionPolicy,
    FieldMapping,
    ManagedResourceSpec,
    NameRule,
    OwnershipPolicy,
    RBACRule,
    ReconcileStrategy,
    ResourceCapability,
    ResourceScope,
    StatusMapping,
)


@dataclass(frozen=True)
class ResourceDefaults:
    api_version: str
    canonical_kind: str
    suffix: str
    scope: ResourceScope = ResourceScope.NAMESPACED
    strategy: ReconcileStrategy = ReconcileStrategy.CREATE_OR_UPDATE
    ownership: OwnershipPolicy = OwnershipPolicy.OWNER_REFERENCE
    deletion_policy: DeletionPolicy = DeletionPolicy.GARBAGE_COLLECT


RESOURCE_DEFAULTS = {
    "ConfigMap": ResourceDefaults("v1", "ConfigMap", "config"),
    "Secret": ResourceDefaults("v1", "Secret", "secret"),
    "PVC": ResourceDefaults("v1", "PersistentVolumeClaim", "pvc"),
    "PersistentVolumeClaim": ResourceDefaults(
        "v1",
        "PersistentVolumeClaim",
        "pvc",
    ),
    "CronJob": ResourceDefaults("batch/v1", "CronJob", "cronjob"),
    "Deployment": ResourceDefaults("apps/v1", "Deployment", "deployment"),
    "Service": ResourceDefaults("v1", "Service", "service"),
    "Namespace": ResourceDefaults(
        "v1",
        "Namespace",
        "namespace",
        scope=ResourceScope.CLUSTER,
        strategy=ReconcileStrategy.PATCH_EXISTING,
        ownership=OwnershipPolicy.NONE,
        deletion_policy=DeletionPolicy.RETAIN,
    ),
    "Pod": ResourceDefaults(
        "v1",
        "Pod",
        "pod",
        strategy=ReconcileStrategy.READ_ONLY,
        ownership=OwnershipPolicy.NONE,
        deletion_policy=DeletionPolicy.RETAIN,
    ),
    "Job": ResourceDefaults(
        "batch/v1",
        "Job",
        "job",
        strategy=ReconcileStrategy.READ_ONLY,
        ownership=OwnershipPolicy.NONE,
        deletion_policy=DeletionPolicy.RETAIN,
    ),
}

NAME_FIELDS = {
    "ConfigMap": ("configMapName", "name"),
    "Secret": ("secretName", "targetName", "name"),
    "PersistentVolumeClaim": ("claimName", "pvcName"),
    "CronJob": ("cronJobName",),
    "Deployment": ("deploymentName", "appName"),
    "Service": ("serviceName", "appName"),
    "Namespace": ("namespaceName",),
}

DEFAULT_FIELD_MAPPINGS = {
    "ConfigMap": (("configData", "data"), ("data", "data")),
    "Secret": (("data", "stringData"), ("secretData", "stringData")),
    "PersistentVolumeClaim": (
        ("storageSize", "spec.resources.requests.storage"),
        ("size", "spec.resources.requests.storage"),
        ("storageClassName", "spec.storageClassName"),
        ("accessModes", "spec.accessModes"),
    ),
    "CronJob": (
        ("schedule", "spec.schedule"),
        ("image", "spec.jobTemplate.spec.template.spec.containers[0].image"),
        ("command", "spec.jobTemplate.spec.template.spec.containers[0].command"),
        ("suspend", "spec.suspend"),
    ),
    "Deployment": (
        ("image", "spec.template.spec.containers[0].image"),
        ("replicas", "spec.replicas"),
        ("size", "spec.replicas"),
        ("port", "spec.template.spec.containers[0].ports[0].containerPort"),
        ("containerPort", "spec.template.spec.containers[0].ports[0].containerPort"),
    ),
    "Service": (
        ("port", "spec.ports[0].port"),
    ),
    "Namespace": (
        ("labels", "metadata.labels"),
    ),
}

STATUS_RESOURCE_FIELDS = {
    "configMapName": ("ConfigMap", "metadata.name", "resource-name"),
    "secretName": ("Secret", "metadata.name", "resource-name"),
    "claimName": ("PersistentVolumeClaim", "metadata.name", "resource-name"),
    "cronJobName": ("CronJob", "metadata.name", "resource-name"),
    "deploymentName": ("Deployment", "metadata.name", "resource-name"),
    "serviceName": ("Service", "metadata.name", "resource-name"),
    "observedNamespace": ("Namespace", "metadata.name", "resource-name"),
    "readyReplicas": (
        "Deployment",
        "status.availableReplicas",
        "direct",
    ),
    "lastScheduleTime": (
        "CronJob",
        "status.lastScheduleTime",
        "direct",
    ),
}


def build_controller_ir(model: dict[str, Any]) -> ControllerGenerationIR:
    api = model["api"]
    fields = field_names(model.get("specFields") or [])
    status_fields = field_names(model.get("statusFields") or [])
    explicit_mappings = parse_explicit_mappings(
        (model.get("controller") or {}).get("fieldMappings") or []
    )
    resources = []
    seen = set()
    for raw_kind in (
        (model.get("controller") or {}).get("managedResources") or []
    ):
        defaults = RESOURCE_DEFAULTS.get(str(raw_kind))
        if not defaults or defaults.canonical_kind in seen:
            continue
        seen.add(defaults.canonical_kind)
        resources.append(
            build_managed_resource(
                defaults,
                fields,
                status_fields,
                explicit_mappings,
            )
        )
    return ControllerGenerationIR(
        project_module=str((model.get("project") or {}).get("module") or ""),
        api_group=str(api.get("group") or ""),
        api_version=str(api.get("version") or ""),
        kind=str(api.get("kind") or ""),
        spec_fields=sorted(fields),
        status_fields=sorted(status_fields),
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
    defaults: ResourceDefaults,
    fields: set[str],
    status_fields: set[str],
    explicit_mappings: list[FieldMapping],
) -> ManagedResourceSpec:
    kind = defaults.canonical_kind
    name_field = first_field(fields, *NAME_FIELDS.get(kind, ()))
    capabilities = capabilities_for(defaults)
    mappings = mappings_for(kind, fields, explicit_mappings)
    return ManagedResourceSpec(
        resource_id=kind[:1].lower() + kind[1:],
        api_version=defaults.api_version,
        kind=kind,
        scope=defaults.scope,
        name=NameRule(
            source_path=f"spec.{name_field}" if name_field else "",
            fallback_template=f"{{metadata.name}}-{defaults.suffix}",
        ),
        strategy=defaults.strategy,
        capabilities=capabilities,
        ownership=defaults.ownership,
        deletion_policy=defaults.deletion_policy,
        watch=ResourceCapability.WATCH in capabilities,
        field_mappings=mappings,
        status_mappings=status_mappings_for(kind, status_fields),
        disable_when=(
            "spec.enabled == false"
            if kind in {"ConfigMap", "Secret"} and "enabled" in fields
            else ""
        ),
    )


def capabilities_for(
    defaults: ResourceDefaults,
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
    kind: str,
    fields: set[str],
    explicit: list[FieldMapping],
) -> list[FieldMapping]:
    result = [
        item
        for item in explicit
        if target_resource(item.target_path) == kind
    ]
    existing_pairs = {
        (item.source_path, item.target_path)
        for item in result
    }
    for field, target in DEFAULT_FIELD_MAPPINGS.get(kind, ()):
        source = f"spec.{field}"
        if field in fields and (source, target) not in existing_pairs:
            result.append(
                FieldMapping(
                    source_path=source,
                    target_path=target,
                )
            )
    return result


def status_mappings_for(
    kind: str,
    status_fields: set[str],
) -> list[StatusMapping]:
    result = []
    for field in status_fields:
        mapping = STATUS_RESOURCE_FIELDS.get(field)
        if not mapping or mapping[0] != kind:
            continue
        result.append(
            StatusMapping(
                source_path=mapping[1],
                target_path=f"status.{field}",
                transform=mapping[2],
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
    aliases = {
        "PVC": "PersistentVolumeClaim",
        "PersistentVolumeClaim": "PersistentVolumeClaim",
    }
    return aliases.get(prefix, prefix)


def field_names(values: list[Any]) -> set[str]:
    return {
        str(item.get("name"))
        for item in values
        if isinstance(item, dict) and item.get("name")
    }


def first_field(fields: set[str], *candidates: str) -> str:
    return next((item for item in candidates if item in fields), "")
