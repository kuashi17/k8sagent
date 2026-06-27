"""Render profile-less Controller behavior from a generalized Operator spec."""

from __future__ import annotations

from typing import Any

from agent.tools.controller_ir import (
    ControllerGenerationIR,
    ManagedResourceSpec,
    OwnershipPolicy,
    ReconcileStrategy,
    ResourceScope,
)
from agent.tools.controller_ir_builder import build_controller_ir
from agent.tools.controller_emitters import (
    render_dependencies,
    render_mutations,
    render_recreate_guard,
)


def render_controller(model: dict[str, Any]) -> str:
    ir = build_controller_ir(model)
    kind = ir.kind
    alias = api_alias(ir.api_group, ir.api_version)
    resources = ir.renderable_resources()
    if not resources:
        raise SystemExit(
            "profile-less controller generation requires at least one "
            "supported managed resource"
        )

    reconcile_calls = []
    functions = []
    for resource in resources:
        variable = resource.resource_id
        reconcile_calls.append(
            f"\t{variable}Name, err := "
            f"r.reconcile{go_name(resource.resource_id)}"
            f"(ctx, &instance)\n"
            "\tif err != nil {\n"
            f'\t\t_ = r.updateStatus(ctx, &instance, "Error", err.Error(), names)\n'
            "\t\treturn ctrl.Result{}, err\n"
            "\t}\n"
            f'\tnames["{resource.kind}"] = {variable}Name'
        )
        functions.append(render_resource_function(resource, ir, alias))

    return f'''package controller

import (
\t"context"
\t"fmt"
\t"reflect"
\t"sort"{render_status_imports(ir)}

\tapierrors "k8s.io/apimachinery/pkg/api/errors"
\t"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
\t"k8s.io/apimachinery/pkg/runtime"
\t"k8s.io/apimachinery/pkg/runtime/schema"
\tctrl "sigs.k8s.io/controller-runtime"
\t"sigs.k8s.io/controller-runtime/pkg/client"
\t"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"

\t{alias} "{ir.project_module}/api/{ir.api_version}"
)

type {kind}Reconciler struct {{
\tclient.Client
\tScheme *runtime.Scheme
}}

{render_marker_block(ir)}

func (r *{kind}Reconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {{
\tvar instance {alias}.{kind}
\tif err := r.Get(ctx, req.NamespacedName, &instance); err != nil {{
\t\tif apierrors.IsNotFound(err) {{
\t\t\treturn ctrl.Result{{}}, nil
\t\t}}
\t\treturn ctrl.Result{{}}, err
\t}}

\tnames := map[string]string{{}}
{chr(10).join(reconcile_calls)}
\treturn ctrl.Result{{}}, r.updateStatus(ctx, &instance, "Ready", "Managed resources are reconciled.", names)
}}

{chr(10).join(functions)}
{render_status_function(ir, alias)}

func managedObject(group, version, kind, namespace, name string) *unstructured.Unstructured {{
\tobject := &unstructured.Unstructured{{}}
\tobject.SetGroupVersionKind(schema.GroupVersionKind{{
\t\tGroup: group,
\t\tVersion: version,
\t\tKind: kind,
\t}})
\tobject.SetNamespace(namespace)
\tobject.SetName(name)
\treturn object
}}

func setOwner(owner client.Object, object client.Object, scheme *runtime.Scheme) error {{
\treturn controllerutil.SetControllerReference(owner, object, scheme)
}}

func stringMapToInterface(input map[string]string) map[string]interface{{}} {{
\toutput := make(map[string]interface{{}}, len(input))
\tfor key, value := range input {{
\t\toutput[key] = value
\t}}
\treturn output
}}

func stringSliceToInterface(input []string) []interface{{}} {{
\toutput := make([]interface{{}}, len(input))
\tfor index, value := range input {{
\t\toutput[index] = value
\t}}
\treturn output
}}

func envMapToInterface(input map[string]string) []interface{{}} {{
\tkeys := make([]string, 0, len(input))
\tfor key := range input {{
\t\tkeys = append(keys, key)
\t}}
\tsort.Strings(keys)
\toutput := make([]interface{{}}, 0, len(keys))
\tfor _, key := range keys {{
\t\toutput = append(output, map[string]interface{{}}{{
\t\t\t"name": key,
\t\t\t"value": input[key],
\t\t}})
\t}}
\treturn output
}}

func mergeNestedMap(target, source map[string]interface{{}}) {{
\tfor key, value := range source {{
\t\tsourceMap, nested := value.(map[string]interface{{}})
\t\tif !nested {{
\t\t\ttarget[key] = value
\t\t\tcontinue
\t\t}}
\t\ttargetMap, ok := target[key].(map[string]interface{{}})
\t\tif !ok {{
\t\t\ttargetMap = map[string]interface{{}}{{}}
\t\t}}
\t\tmergeNestedMap(targetMap, sourceMap)
\t\ttarget[key] = targetMap
\t}}
}}

func mergeStringMapAtPath(current map[string]interface{{}}, path []interface{{}}, input map[string]string) error {{
\tmerged := map[string]interface{{}}{{}}
\tif existing, found := nestedValue(current, path); found {{
\t\tif values, ok := existing.(map[string]interface{{}}); ok {{
\t\t\tfor key, value := range values {{
\t\t\t\tmerged[key] = value
\t\t\t}}
\t\t}}
\t}}
\tfor key, value := range input {{
\t\tmerged[key] = value
\t}}
\treturn setNestedValue(current, path, merged)
}}

func nestedValue(current interface{{}}, path []interface{{}}) (interface{{}}, bool) {{
\tif len(path) == 0 {{
\t\treturn current, true
\t}}
\tswitch node := current.(type) {{
\tcase map[string]interface{{}}:
\t\tkey, ok := path[0].(string)
\t\tif !ok {{
\t\t\treturn nil, false
\t\t}}
\t\tchild, found := node[key]
\t\tif !found {{
\t\t\treturn nil, false
\t\t}}
\t\treturn nestedValue(child, path[1:])
\tcase []interface{{}}:
\t\tindex, ok := path[0].(int)
\t\tif !ok || index < 0 || index >= len(node) {{
\t\t\treturn nil, false
\t\t}}
\t\treturn nestedValue(node[index], path[1:])
\tdefault:
\t\treturn nil, false
\t}}
}}

func setNestedValue(current interface{{}}, path []interface{{}}, value interface{{}}) error {{
\t_, err := assignNestedValue(current, path, value)
\treturn err
}}

func assignNestedValue(current interface{{}}, path []interface{{}}, value interface{{}}) (interface{{}}, error) {{
\tif len(path) == 0 {{
\t\treturn current, fmt.Errorf("nested path is empty")
\t}}
\tswitch node := current.(type) {{
\tcase map[string]interface{{}}:
\t\tkey, ok := path[0].(string)
\t\tif !ok {{
\t\t\treturn current, fmt.Errorf("expected map key, got %T", path[0])
\t\t}}
\t\tif len(path) == 1 {{
\t\t\tnode[key] = value
\t\t\treturn node, nil
\t\t}}
\t\tchild, exists := node[key]
\t\tif !exists || child == nil {{
\t\t\tif _, isIndex := path[1].(int); isIndex {{
\t\t\t\tchild = []interface{{}}{{}}
\t\t\t}} else {{
\t\t\t\tchild = map[string]interface{{}}{{}}
\t\t\t}}
\t\t\tnode[key] = child
\t\t}}
\t\tupdated, err := assignNestedValue(child, path[1:], value)
\t\tif err != nil {{
\t\t\treturn current, err
\t\t}}
\t\tnode[key] = updated
\t\treturn node, nil
\tcase []interface{{}}:
\t\tindex, ok := path[0].(int)
\t\tif !ok {{
\t\t\treturn current, fmt.Errorf("expected list index, got %T", path[0])
\t\t}}
\t\tfor len(node) <= index {{
\t\t\tnode = append(node, nil)
\t\t}}
\t\tif len(path) == 1 {{
\t\t\tnode[index] = value
\t\t\treturn node, nil
\t\t}}
\t\tchild := node[index]
\t\tif child == nil {{
\t\t\tif _, isIndex := path[1].(int); isIndex {{
\t\t\t\tchild = []interface{{}}{{}}
\t\t\t}} else {{
\t\t\t\tchild = map[string]interface{{}}{{}}
\t\t\t}}
\t\t\tnode[index] = child
\t\t}}
\t\tupdated, err := assignNestedValue(child, path[1:], value)
\t\tif err != nil {{
\t\t\treturn current, err
\t\t}}
\t\tnode[index] = updated
\t\treturn node, nil
\tdefault:
\t\treturn current, fmt.Errorf("cannot descend into %T", current)
\t}}
}}

func (r *{kind}Reconciler) SetupWithManager(mgr ctrl.Manager) error {{
\treturn ctrl.NewControllerManagedBy(mgr).
\t\tFor(&{alias}.{kind}{{}}){render_owned_watches(ir)}.
\t\tComplete(r)
}}
'''


def render_resource_function(
    resource: ManagedResourceSpec,
    ir: ControllerGenerationIR,
    alias: str,
) -> str:
    kind = ir.kind
    group, version = split_api_version(resource.api_version)
    function_name = go_name(resource.resource_id)
    name_expression = source_expression(resource.name.source_path)
    suffix = resource.name.fallback_template.replace(
        "{metadata.name}-",
        "",
    )
    namespace = (
        '""'
        if resource.scope == ResourceScope.CLUSTER
        else "instance.Namespace"
    )
    mutations = render_mutations(resource, ir)
    dependencies = render_dependencies(resource, ir)
    disable_guard = render_disable_guard(
        resource,
        namespace,
    )
    recreate_guard = render_recreate_guard(resource)
    owner = (
        ""
        if resource.ownership == OwnershipPolicy.NONE
        else "\t\treturn setOwner(instance, object, r.Scheme)\n"
    )
    final_return = (
        "\t\treturn nil\n"
        if resource.ownership == OwnershipPolicy.NONE
        else owner
    )
    if resource.strategy == ReconcileStrategy.PATCH_EXISTING:
        return render_patch_existing_function(
            resource,
            ir,
            alias,
            group,
            version,
            function_name,
            name_expression,
            suffix,
            namespace,
            mutations,
        )
    return f'''func (r *{kind}Reconciler) reconcile{function_name}(ctx context.Context, instance *{alias}.{kind}) (string, error) {{
\tname := {name_expression}
\tif name == "" {{
\t\tname = instance.Name + "-{suffix}"
\t}}
{dependencies}
\tobject := managedObject("{group}", "{version}", "{resource.kind}", {namespace}, name)
{disable_guard}
{recreate_guard}
\t_, err := controllerutil.CreateOrUpdate(ctx, r.Client, object, func() error {{
\t\tlabels := object.GetLabels()
\t\tif labels == nil {{
\t\t\tlabels = map[string]string{{}}
\t\t}}
\t\tlabels["app.kubernetes.io/managed-by"] = "{ir.kind.lower()}-operator"
\t\tlabels["operator.sample.io/owner"] = instance.Name
\t\tobject.SetLabels(labels)
{mutations}
{final_return}\t}})
\tif err != nil {{
\t\treturn name, fmt.Errorf("reconcile {resource.kind}: %w", err)
\t}}
\treturn name, nil
}}
'''


def render_patch_existing_function(
    resource: ManagedResourceSpec,
    ir: ControllerGenerationIR,
    alias: str,
    group: str,
    version: str,
    function_name: str,
    name_expression: str,
    suffix: str,
    namespace: str,
    mutations: str,
) -> str:
    return f'''func (r *{ir.kind}Reconciler) reconcile{function_name}(ctx context.Context, instance *{alias}.{ir.kind}) (string, error) {{
\tname := {name_expression}
\tif name == "" {{
\t\tname = instance.Name + "-{suffix}"
\t}}
\tobject := managedObject("{group}", "{version}", "{resource.kind}", {namespace}, name)
\tif err := r.Get(ctx, client.ObjectKey{{Namespace: {namespace}, Name: name}}, object); err != nil {{
\t\treturn name, fmt.Errorf("get {resource.kind}: %w", err)
\t}}
\tlabels := object.GetLabels()
\tif labels == nil {{
\t\tlabels = map[string]string{{}}
\t}}
\tlabels["app.kubernetes.io/managed-by"] = "{ir.kind.lower()}-operator"
\tlabels["operator.sample.io/owner"] = instance.Name
\tobject.SetLabels(labels)
{dedent_mutations(mutations)}
\tif err := r.Update(ctx, object); err != nil {{
\t\treturn name, fmt.Errorf("update {resource.kind}: %w", err)
\t}}
\treturn name, nil
}}
'''


def dedent_mutations(value: str) -> str:
    dedented = "\n".join(
        line.removeprefix("\t")
        if line.startswith("\t")
        else line
        for line in value.splitlines()
    )
    return dedented.replace("{ return err }", "{ return name, err }")


def render_disable_guard(
    resource: ManagedResourceSpec,
    namespace: str,
) -> str:
    if not resource.disable_when:
        return ""
    return f'''\tif !instance.Spec.Enabled {{
\t\terr := r.Get(ctx, client.ObjectKey{{Namespace: {namespace}, Name: name}}, object)
\t\tif err == nil {{
\t\t\treturn name, r.Delete(ctx, object)
\t\t}}
\t\tif !apierrors.IsNotFound(err) {{
\t\t\treturn name, err
\t\t}}
\t\treturn name, nil
\t}}'''


def render_status_function(
    ir: ControllerGenerationIR,
    alias: str,
) -> str:
    kind = ir.kind
    status_fields = set(ir.status_fields)
    assignments = []
    if "phase" in status_fields:
        assignments.append("\tinstance.Status.Phase = phase")
    if "message" in status_fields:
        assignments.append("\tinstance.Status.Message = message")
    for resource in ir.managed_resources:
        for mapping in resource.status_mappings:
            field = mapping.target_path.removeprefix("status.")
            if mapping.transform == "resource-name":
                assignments.append(
                    f'\tinstance.Status.{go_name(field)} = '
                    f'names["{resource.kind}"]'
                )
            else:
                assignments.extend(
                    render_direct_status_mapping(resource, mapping, field)
                )
    return f'''func (r *{kind}Reconciler) updateStatus(ctx context.Context, instance *{alias}.{kind}, phase, message string, names map[string]string) error {{
\tbefore := instance.DeepCopy()
{chr(10).join(assignments)}
\tif reflect.DeepEqual(before.Status, instance.Status) {{
\t\treturn nil
\t}}
\treturn r.Status().Update(ctx, instance)
}}
'''


def render_direct_status_mapping(
    resource: ManagedResourceSpec,
    mapping: Any,
    field: str,
) -> list[str]:
    group, version = split_api_version(resource.api_version)
    variable = f"{resource.resource_id}{go_name(field)}"
    namespace = (
        '""'
        if resource.scope == ResourceScope.CLUSTER
        else "instance.Namespace"
    )
    path = ", ".join(
        f'"{part}"'
        for part in mapping.source_path.split(".")
        if part
    )
    lines = [
        f'\tif names["{resource.kind}"] != "" {{',
        (
            f'\t\t{variable}Object := managedObject("{group}", "{version}", '
            f'"{resource.kind}", {namespace}, names["{resource.kind}"])'
        ),
        (
            f"\t\tif err := r.Get(ctx, client.ObjectKey{{Namespace: {namespace}, "
            f'Name: names["{resource.kind}"]}}, {variable}Object); err == nil {{'
        ),
    ]
    lines.extend(
        render_status_value_assignment(
            variable,
            path,
            f"instance.Status.{go_name(field)}",
            mapping.target_type,
        )
    )
    lines.extend(
        [
            "\t\t} else if !apierrors.IsNotFound(err) {",
            "\t\t\treturn err",
            "\t\t}",
            "\t}",
        ]
    )
    return lines


def render_status_value_assignment(
    variable: str,
    path: str,
    target: str,
    target_type: str,
) -> list[str]:
    normalized = target_type.strip()
    if normalized in {"int", "int32", "int64"}:
        assignment = (
            f"int32({variable}Value)"
            if normalized in {"int", "int32"}
            else f"{variable}Value"
        )
        return [
            (
                f"\t\t\t{variable}Value, found, nestedErr := "
                f"unstructured.NestedInt64({variable}Object.Object, {path})"
            ),
            "\t\t\tif nestedErr != nil { return nestedErr }",
            f"\t\t\tif found {{ {target} = {assignment} }}",
        ]
    if normalized in {"bool", "boolean"}:
        return [
            (
                f"\t\t\t{variable}Value, found, nestedErr := "
                f"unstructured.NestedBool({variable}Object.Object, {path})"
            ),
            "\t\t\tif nestedErr != nil { return nestedErr }",
            f"\t\t\tif found {{ {target} = {variable}Value }}",
        ]
    if normalized == "metav1.Time":
        return [
            (
                f"\t\t\t{variable}Value, found, nestedErr := "
                f"unstructured.NestedString({variable}Object.Object, {path})"
            ),
            "\t\t\tif nestedErr != nil { return nestedErr }",
            "\t\t\tif found {",
            (
                f"\t\t\t\tparsed, parseErr := time.Parse(time.RFC3339, "
                f"{variable}Value)"
            ),
            "\t\t\t\tif parseErr != nil { return parseErr }",
            f"\t\t\t\t{target} = metav1.NewTime(parsed)",
            "\t\t\t}",
        ]
    return [
        (
            f"\t\t\t{variable}Value, found, nestedErr := "
            f"unstructured.NestedString({variable}Object.Object, {path})"
        ),
        "\t\t\tif nestedErr != nil { return nestedErr }",
        f"\t\t\tif found {{ {target} = {variable}Value }}",
    ]


def render_owned_watches(ir: ControllerGenerationIR) -> str:
    lines = []
    for resource in ir.managed_resources:
        if not resource.watch:
            continue
        if resource.ownership != OwnershipPolicy.OWNER_REFERENCE:
            continue
        group, version = split_api_version(resource.api_version)
        lines.append(
            '.\n\t\tOwns(managedObject('
            f'"{group}", "{version}", "{resource.kind}", "", ""))'
        )
    return "".join(lines)


def render_status_imports(ir: ControllerGenerationIR) -> str:
    if not any(
        mapping.target_type == "metav1.Time"
        for resource in ir.managed_resources
        for mapping in resource.status_mappings
    ):
        return ""
    return (
        '\n\t"time"\n'
        '\n\tmetav1 "k8s.io/apimachinery/pkg/apis/meta/v1"'
    )


def render_marker_block(ir: ControllerGenerationIR) -> str:
    lines = []
    for item in ir.rbac_rules:
        group = item.api_group
        group_value = '""' if group == "" else group
        verbs = ";".join(item.verbs)
        lines.append(
            f"// +kubebuilder:rbac:groups={group_value},"
            f"resources={item.resource},verbs={verbs}"
        )
    return "\n".join(lines)


def source_expression(path: str) -> str:
    if not path:
        return '""'
    if path.startswith("spec."):
        return f"instance.Spec.{go_name(path.removeprefix('spec.'))}"
    return '""'


def split_api_version(api_version: str) -> tuple[str, str]:
    if "/" not in api_version:
        return "", api_version
    group, version = api_version.split("/", 1)
    return group, version


def api_alias(group: str, version: str) -> str:
    return f"{group}{version}".replace("-", "")


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
