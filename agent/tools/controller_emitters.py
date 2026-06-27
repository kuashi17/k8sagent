"""Behavior emitters used by the generic Controller renderer."""

from __future__ import annotations

from collections.abc import Callable
import re
from typing import Any

from agent.tools.controller_ir import (
    ControllerGenerationIR,
    ManagedResourceSpec,
)


Emitter = Callable[[ManagedResourceSpec, ControllerGenerationIR], str]


def render_mutations(
    resource: ManagedResourceSpec,
    ir: ControllerGenerationIR,
) -> str:
    try:
        emitter = EMITTERS[resource.emitter]
    except KeyError as exc:
        raise ValueError(
            f"unsupported controller emitter: {resource.emitter}"
        ) from exc
    return emitter(resource, ir)


def render_dependencies(
    resource: ManagedResourceSpec,
    ir: ControllerGenerationIR,
) -> str:
    if not resource.dependency_kind:
        return ""
    service = next(
        (
            item
            for item in ir.managed_resources
            if item.kind == resource.dependency_kind
        ),
        None,
    )
    variable = resource.dependency_variable or "dependencyName"
    if not service:
        return f"\t{variable} := name"
    expression = source_expression(service.name.source_path)
    suffix = service.name.fallback_template.replace(
        "{metadata.name}-",
        "",
    )
    return f'''\t{variable} := {expression}
\tif {variable} == "" {{
\t\t{variable} = instance.Name + "-{suffix}"
\t}}'''


def emit_string_map(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    mapping = first_mapping(resource)
    if not mapping:
        return ""
    target = nested_path(mapping.target_path)
    return (
        "\t\tif err := unstructured.SetNestedStringMap("
        "object.Object, copyStringMap("
        f"instance.Spec.{go_name(source_field(mapping.source_path))}), "
        f"{target}); err != nil {{ return err }}"
    )


def emit_storage_claim(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    lines = []
    for mapping in resource.field_mappings:
        source = f"instance.Spec.{go_name(source_field(mapping.source_path))}"
        if mapping.target_path == "spec.resources.requests.storage":
            lines.append(
                "\t\tif err := unstructured.SetNestedMap(object.Object, "
                'map[string]interface{}{"requests": '
                f'map[string]interface{{}}{{"storage": {source}}}}}, '
                '"spec", "resources"); err != nil { return err }'
            )
        elif mapping.target_path == "spec.storageClassName":
            lines.append(
                "\t\tif err := unstructured.SetNestedField("
                f'object.Object, {source}, "spec", '
                '"storageClassName"); err != nil { return err }'
            )
        elif mapping.target_path == "spec.accessModes":
            lines.extend(
                [
                    f"\t\tvalues := make([]interface{{}}, len({source}))",
                    (
                        f"\t\tfor index, value := range {source} "
                        "{ values[index] = value }"
                    ),
                    (
                        "\t\tif err := unstructured.SetNestedSlice("
                        'object.Object, values, "spec", "accessModes"); '
                        "err != nil { return err }"
                    ),
                ]
            )
    return "\n".join(lines)


def emit_stateful_workload(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    sources = source_by_target(resource)
    lines = workload_container(sources)
    storage = sources.get(
        "spec.volumeClaimTemplates[0].spec.resources.requests.storage"
    )
    if storage:
        lines.append(
            '\t\tcontainer["volumeMounts"] = []interface{}{'
            'map[string]interface{}{"name": "data", "mountPath": "/data"}}'
        )
    lines.extend(
        [
            "\t\tnestedLabels := stringMapToInterface(labels)",
            (
                '\t\ttemplate := map[string]interface{}{"metadata": '
                'map[string]interface{}{"labels": nestedLabels}, '
                '"spec": map[string]interface{}'
                '{"containers": []interface{}{container}}}'
            ),
            (
                '\t\tresourceSpec := map[string]interface{}'
                '{"serviceName": serviceName, "selector": '
                'map[string]interface{}{"matchLabels": nestedLabels}, '
                '"template": template}'
            ),
        ]
    )
    replicas = sources.get("spec.replicas")
    if replicas:
        lines.append(
            '\t\tresourceSpec["replicas"] = int64('
            f"{source_expression(replicas)})"
        )
    if storage:
        lines.append(
            '\t\tresourceSpec["volumeClaimTemplates"] = []interface{}{'
            'map[string]interface{}{"metadata": map[string]interface{}'
            '{"name": "data"}, "spec": map[string]interface{}'
            '{"accessModes": []interface{}{"ReadWriteOnce"}, '
            '"resources": map[string]interface{}{"requests": '
            'map[string]interface{}{"storage": '
            f"{source_expression(storage)}"
            "}}}}}"
        )
    lines.append(set_spec("resourceSpec"))
    return "\n".join(lines)


def emit_label_patch(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    mapping = first_mapping(resource)
    if not mapping:
        return ""
    expression = source_expression(mapping.source_path)
    return (
        f"\t\tfor key, value := range {expression} "
        "{ labels[key] = value }\n"
        "\t\tobject.SetLabels(labels)"
    )


def emit_generic_object(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    lines = [
        f"\t\tresourceSpec := {go_literal(resource.base_spec)}",
    ]
    if resource.label_paths:
        lines.append(
            "\t\tnestedLabels := stringMapToInterface(labels)"
        )
        for path in resource.label_paths:
            lines.append(
                "\t\tif err := setNestedValue(resourceSpec, "
                f"{go_path(path)}, nestedLabels); err != nil "
                "{ return err }"
            )
    for mapping in resource.field_mappings:
        target = mapping.target_path.removeprefix("spec.")
        lines.append(
            "\t\tif err := setNestedValue(resourceSpec, "
            f"{go_path(target)}, {mapping_value(mapping)}); "
            "err != nil { return err }"
        )
    lines.append(set_spec("resourceSpec"))
    return "\n".join(lines)


def workload_container(sources: dict[str, str]) -> list[str]:
    image = source_expression(
        sources.get("spec.template.spec.containers[0].image", "spec.image")
    )
    lines = [
        (
            "\t\tcontainer := map[string]interface{}"
            f'{{"name": "application", "image": {image}}}'
        )
    ]
    port = sources.get(
        "spec.template.spec.containers[0].ports[0].containerPort"
    )
    if port:
        lines.append(
            '\t\tcontainer["ports"] = []interface{}{'
            'map[string]interface{}{"containerPort": int64('
            f"{source_expression(port)})"
            "}}"
        )
    return lines


def set_spec(variable: str) -> str:
    return (
        "\t\tif err := unstructured.SetNestedMap("
        f'object.Object, {variable}, "spec"); err != nil '
        "{ return err }"
    )


def first_mapping(resource: ManagedResourceSpec):
    return next(iter(resource.field_mappings), None)


def source_by_target(resource: ManagedResourceSpec) -> dict[str, str]:
    return {
        item.target_path: item.source_path
        for item in resource.field_mappings
    }


def source_field(path: str) -> str:
    return path.removeprefix("spec.")


def source_expression(path: str) -> str:
    if path.startswith("spec."):
        return f"instance.Spec.{go_name(source_field(path))}"
    return '""'


def mapping_value(mapping: Any) -> str:
    expression = source_expression(mapping.source_path)
    if mapping.transform == "int64":
        return f"int64({expression})"
    if mapping.transform == "string-slice":
        return f"stringSliceToInterface({expression})"
    if mapping.transform == "string-map":
        return f"stringMapToInterface({expression})"
    return expression


def go_path(path: str) -> str:
    tokens: list[str] = []
    for part in path.split("."):
        match = re.fullmatch(r"([^\[]+)(?:\[(\d+)\])?", part)
        if not match:
            raise ValueError(f"unsupported nested target path: {path}")
        key, index = match.groups()
        tokens.append(f'"{key}"')
        if index is not None:
            tokens.append(index)
    return "[]interface{}{" + ", ".join(tokens) + "}"


def go_literal(value: Any) -> str:
    if isinstance(value, dict):
        items = ", ".join(
            f'"{key}": {go_literal(item)}'
            for key, item in value.items()
        )
        return f"map[string]interface{{}}{{{items}}}"
    if isinstance(value, list):
        return "[]interface{}{" + ", ".join(
            go_literal(item) for item in value
        ) + "}"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if value is None:
        return "nil"
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def nested_path(path: str) -> str:
    return ", ".join(
        f'"{part}"' for part in path.split(".") if part
    )


def go_name(value: str) -> str:
    result = value[:1].upper() + value[1:]
    for old, new in {
        "Pvc": "PVC",
        "Gpu": "GPU",
        "Id": "ID",
        "Url": "URL",
    }.items():
        if result.startswith(old):
            result = new + result[len(old) :]
    return result


EMITTERS: dict[str, Emitter] = {
    "string-map": emit_string_map,
    "storage-claim": emit_storage_claim,
    "stateful-workload": emit_stateful_workload,
    "label-patch": emit_label_patch,
    "generic-object": emit_generic_object,
}
