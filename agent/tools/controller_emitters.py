"""Behavior emitters used by the generic Controller renderer."""

from __future__ import annotations

import re
from typing import Any

from agent.tools.controller_ir import (
    ControllerGenerationIR,
    ManagedResourceSpec,
    UpdatePolicy,
)


def render_mutations(
    resource: ManagedResourceSpec,
    _: ControllerGenerationIR,
) -> str:
    """Render one data-driven object mutation path for every resource."""
    lines: list[str] = []
    if resource.base_object:
        lines.extend(
            [
                f"\t\tbaseObject := {go_literal(resource.base_object)}",
                "\t\tmergeNestedMap(object.Object, baseObject)",
            ]
        )
    if resource.label_paths:
        lines.append(
            "\t\tnestedLabels := stringMapToInterface(labels)"
        )
        for path in resource.label_paths:
            lines.append(
                "\t\tif err := setNestedValue(object.Object, "
                f"{go_path(path)}, nestedLabels); err != nil "
                "{ return err }"
            )
    if resource.dependency_target_path:
        lines.append(
            "\t\tif err := setNestedValue(object.Object, "
            f"{go_path(resource.dependency_target_path)}, "
            f"{resource.dependency_variable}); err != nil "
            "{ return err }"
        )
    for mutation in resource.static_mutations:
        lines.append(
            "\t\tif err := setNestedValue(object.Object, "
            f"{go_path(mutation.target_path)}, "
            f"{static_value(mutation.value, mutation.transform)}); "
            "err != nil { return err }"
        )
    for mapping in resource.field_mappings:
        if mapping.transform == "merge-string-map":
            lines.append(
                "\t\tif err := mergeStringMapAtPath(object.Object, "
                f"{go_path(mapping.target_path)}, "
                f"{source_expression(mapping.source_path)}); "
                "err != nil { return err }"
            )
            continue
        lines.append(
            "\t\tif err := setNestedValue(object.Object, "
            f"{go_path(mapping.target_path)}, {mapping_value(mapping)}); "
            "err != nil { return err }"
        )
    return "\n".join(lines)


def render_dependencies(
    resource: ManagedResourceSpec,
    ir: ControllerGenerationIR,
) -> str:
    if not resource.dependency_kind:
        return ""
    dependency = next(
        (
            item
            for item in ir.managed_resources
            if item.kind == resource.dependency_kind
        ),
        None,
    )
    variable = resource.dependency_variable
    if not dependency:
        return f"\t{variable} := name"
    expression = source_expression(dependency.name.source_path)
    suffix = dependency.name.fallback_template.replace(
        "{metadata.name}-",
        "",
    )
    return f'''\t{variable} := {expression}
\tif {variable} == "" {{
\t\t{variable} = instance.Name + "-{suffix}"
\t}}'''


def render_recreate_guard(resource: ManagedResourceSpec) -> str:
    mappings = [
        mapping
        for mapping in resource.field_mappings
        if mapping.update_policy == UpdatePolicy.RECREATE
    ]
    if not mappings:
        return ""
    comparisons = []
    for mapping in mappings:
        comparisons.append(
            "\t\tif current, found := nestedValue(object.Object, "
            f"{go_path(mapping.target_path)}); !found || "
            f"!reflect.DeepEqual(current, {mapping_value(mapping)}) {{\n"
            "\t\t\trecreate = true\n"
            "\t\t}"
        )
    return """\tif err := r.Get(ctx, client.ObjectKey{Namespace: object.GetNamespace(), Name: name}, object); err == nil {
\t\trecreate := false
%s
\t\tif recreate {
\t\t\tif err := r.Delete(ctx, object); err != nil {
\t\t\t\treturn name, fmt.Errorf("delete immutable managed resource: %%w", err)
\t\t\t}
\t\t\treturn name, nil
\t\t}
\t} else if !apierrors.IsNotFound(err) {
\t\treturn name, err
\t}
""" % "\n".join(comparisons)


def source_expression(path: str) -> str:
    if path.startswith("spec."):
        return f"instance.Spec.{go_name(source_field(path))}"
    return '""'


def source_field(path: str) -> str:
    return path.removeprefix("spec.")


def mapping_value(mapping: Any) -> str:
    expression = source_expression(mapping.source_path)
    if mapping.transform == "int64":
        return f"int64({expression})"
    if mapping.transform == "string-slice":
        return f"stringSliceToInterface({expression})"
    if mapping.transform == "string-map":
        return f"stringMapToInterface({expression})"
    if mapping.transform == "env-map":
        return f"envMapToInterface({expression})"
    return expression


def static_value(value: Any, transform: str) -> str:
    literal = go_literal(value)
    if transform == "int64":
        return f"int64({literal})"
    if transform == "string-map":
        return literal
    if transform == "string-slice":
        return literal
    return literal


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
