"""Behavior emitters used by the generic Controller renderer."""

from __future__ import annotations

from collections.abc import Callable

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
    if resource.emitter != "stateful-workload":
        return ""
    service = next(
        (
            item
            for item in ir.managed_resources
            if item.emitter == "network-service"
        ),
        None,
    )
    if not service:
        return "\tserviceName := name"
    expression = source_expression(service.name.source_path)
    suffix = service.name.fallback_template.replace(
        "{metadata.name}-",
        "",
    )
    return f'''\tserviceName := {expression}
\tif serviceName == "" {{
\t\tserviceName = instance.Name + "-{suffix}"
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


def emit_scheduled_workload(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    sources = source_by_target(resource)
    image = source_expression(
        sources.get(
            "spec.jobTemplate.spec.template.spec.containers[0].image",
            "spec.image",
        )
    )
    lines = [
        (
            "\t\tcontainer := map[string]interface{}"
            f'{{"name": "task", "image": {image}}}'
        )
    ]
    command = sources.get(
        "spec.jobTemplate.spec.template.spec.containers[0].command"
    )
    if command:
        expression = source_expression(command)
        lines.extend(
            [
                f"\t\tcommand := make([]interface{{}}, len({expression}))",
                (
                    f"\t\tfor index, value := range {expression} "
                    "{ command[index] = value }"
                ),
                '\t\tcontainer["command"] = command',
            ]
        )
    lines.append(
        '\t\tresourceSpec := map[string]interface{}{"jobTemplate": '
        'map[string]interface{}{"spec": map[string]interface{}'
        '{"template": map[string]interface{}{"spec": '
        'map[string]interface{}{"restartPolicy": "Never", '
        '"containers": []interface{}{container}}}}}}'
    )
    append_direct_assignments(
        lines,
        sources,
        {
            "spec.schedule": "schedule",
            "spec.suspend": "suspend",
        },
    )
    lines.append(set_spec("resourceSpec"))
    return "\n".join(lines)


def emit_replicated_workload(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    sources = source_by_target(resource)
    lines = workload_container(sources)
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
                '\t\tresourceSpec := map[string]interface{}{"selector": '
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
    lines.append(set_spec("resourceSpec"))
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


def emit_network_service(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    sources = source_by_target(resource)
    lines = [
        '\t\tresourceSpec := map[string]interface{}'
        '{"selector": stringMapToInterface(labels)}'
    ]
    port = sources.get("spec.ports[0].port")
    if port:
        expression = source_expression(port)
        lines.append(
            '\t\tresourceSpec["ports"] = []interface{}{'
            'map[string]interface{}{"port": int64('
            f"{expression}), \"targetPort\": int64({expression})"
            "}}"
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


def append_direct_assignments(
    lines: list[str],
    sources: dict[str, str],
    targets: dict[str, str],
) -> None:
    for target, key in targets.items():
        source = sources.get(target)
        if source:
            lines.append(
                f'\t\tresourceSpec["{key}"] = '
                f"{source_expression(source)}"
            )


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
    "scheduled-workload": emit_scheduled_workload,
    "replicated-workload": emit_replicated_workload,
    "stateful-workload": emit_stateful_workload,
    "network-service": emit_network_service,
    "label-patch": emit_label_patch,
}
