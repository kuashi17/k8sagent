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
            f"r.reconcile{resource_function(resource.kind)}"
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

func copyStringMap(input map[string]string) map[string]string {{
\toutput := make(map[string]string, len(input))
\tfor key, value := range input {{
\t\toutput[key] = value
\t}}
\treturn output
}}

func (r *{kind}Reconciler) SetupWithManager(mgr ctrl.Manager) error {{
\treturn ctrl.NewControllerManagedBy(mgr).
\t\tFor(&{alias}.{kind}{{}}).
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
    function_name = resource_function(resource.kind)
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
    mutations = render_mutations(resource)
    disable_guard = render_disable_guard(
        resource,
        namespace,
    )
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
\tobject := managedObject("{group}", "{version}", "{resource.kind}", {namespace}, name)
{disable_guard}
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


def render_mutations(resource: ManagedResourceSpec) -> str:
    fields = mapping_source_fields(resource)
    lines: list[str] = []
    if resource.kind == "ConfigMap":
        source = first_field(fields, "configData", "data")
        if source:
            lines.append(
                f'\t\tif err := unstructured.SetNestedStringMap(object.Object, '
                f"copyStringMap(instance.Spec.{go_name(source)}), \"data\"); err != nil {{ return err }}"
            )
    elif resource.kind == "Secret":
        source = first_field(fields, "data", "secretData")
        if source:
            lines.append(
                f'\t\tif err := unstructured.SetNestedStringMap(object.Object, '
                f"copyStringMap(instance.Spec.{go_name(source)}), \"stringData\"); err != nil {{ return err }}"
            )
    elif resource.kind == "PersistentVolumeClaim":
        storage = first_field(fields, "storageSize", "size")
        storage_class = first_field(fields, "storageClassName")
        access_modes = first_field(fields, "accessModes")
        if storage:
            lines.append(
                '\t\tif err := unstructured.SetNestedMap(object.Object, '
                f'map[string]interface{{}}{{"requests": map[string]interface{{}}{{"storage": instance.Spec.{go_name(storage)}}}}}, '
                '"spec", "resources"); err != nil { return err }'
            )
        if storage_class:
            lines.append(
                f'\t\tif err := unstructured.SetNestedField(object.Object, instance.Spec.{go_name(storage_class)}, '
                '"spec", "storageClassName"); err != nil { return err }'
            )
        if access_modes:
            lines.append(
                f'\t\tmodes := make([]interface{{}}, len(instance.Spec.{go_name(access_modes)}))\n'
                f'\t\tfor index, value := range instance.Spec.{go_name(access_modes)} {{ modes[index] = value }}\n'
                '\t\tif err := unstructured.SetNestedSlice(object.Object, modes, "spec", "accessModes"); err != nil { return err }'
            )
    elif resource.kind == "CronJob":
        schedule = first_field(fields, "schedule")
        image = first_field(fields, "image")
        command = first_field(fields, "command")
        suspend = first_field(fields, "suspend")
        container = (
            f'map[string]interface{{}}{{"name": "task", "image": instance.Spec.{go_name(image or "image")}}}'
        )
        lines.append(f"\t\tcontainer := {container}")
        if command:
            lines.append(
                f'\t\tcommand := make([]interface{{}}, len(instance.Spec.{go_name(command)}))\n'
                f'\t\tfor index, value := range instance.Spec.{go_name(command)} {{ command[index] = value }}\n'
                '\t\tcontainer["command"] = command'
            )
        cron_spec = (
            'map[string]interface{}{"jobTemplate": map[string]interface{}{"spec": '
            'map[string]interface{}{"template": map[string]interface{}{"spec": '
            'map[string]interface{}{"restartPolicy": "Never", "containers": '
            '[]interface{}{container}}}}}}'
        )
        lines.append(f"\t\tcronSpec := {cron_spec}")
        if schedule:
            lines.append(
                f'\t\tcronSpec["schedule"] = instance.Spec.{go_name(schedule)}'
            )
        if suspend:
            lines.append(
                f'\t\tcronSpec["suspend"] = instance.Spec.{go_name(suspend)}'
            )
        lines.append(
            '\t\tif err := unstructured.SetNestedMap(object.Object, cronSpec, "spec"); err != nil { return err }'
        )
    elif resource.kind == "Deployment":
        image = first_field(fields, "image")
        replicas = first_field(fields, "replicas", "size")
        port = first_field(fields, "port", "containerPort")
        lines.append(
            f'\t\tcontainer := map[string]interface{{}}{{"name": "application", "image": instance.Spec.{go_name(image or "image")}}}'
        )
        if port:
            lines.append(
                f'\t\tcontainer["ports"] = []interface{{}}{{map[string]interface{{}}{{"containerPort": int64(instance.Spec.{go_name(port)})}}}}'
            )
        lines.append(
            '\t\ttemplate := map[string]interface{}{"metadata": map[string]interface{}{"labels": labels}, '
            '"spec": map[string]interface{}{"containers": []interface{}{container}}}'
        )
        lines.append(
            '\t\tdeploymentSpec := map[string]interface{}{"selector": map[string]interface{}{"matchLabels": labels}, "template": template}'
        )
        if replicas:
            lines.append(
                f'\t\tdeploymentSpec["replicas"] = int64(instance.Spec.{go_name(replicas)})'
            )
        lines.append(
            '\t\tif err := unstructured.SetNestedMap(object.Object, deploymentSpec, "spec"); err != nil { return err }'
        )
    elif resource.kind == "Service":
        port = first_field(fields, "port")
        lines.append(
            '\t\tserviceSpec := map[string]interface{}{"selector": labels}'
        )
        if port:
            lines.append(
                f'\t\tserviceSpec["ports"] = []interface{{}}{{map[string]interface{{}}{{"port": int64(instance.Spec.{go_name(port)}), "targetPort": int64(instance.Spec.{go_name(port)})}}}}'
            )
        lines.append(
            '\t\tif err := unstructured.SetNestedMap(object.Object, serviceSpec, "spec"); err != nil { return err }'
        )
    elif resource.kind == "Namespace":
        labels = first_field(fields, "labels")
        if labels:
            lines.append(
                f"\t\tfor key, value := range instance.Spec.{go_name(labels)} {{ labels[key] = value }}\n"
                "\t\tobject.SetLabels(labels)"
            )
    return "\n".join(lines)


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
            if mapping.transform != "resource-name":
                continue
            field = mapping.target_path.removeprefix("status.")
            assignments.append(
                f'\tinstance.Status.{go_name(field)} = '
                f'names["{resource.kind}"]'
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


def mapping_source_fields(resource: ManagedResourceSpec) -> set[str]:
    return {
        item.source_path.removeprefix("spec.")
        for item in resource.field_mappings
        if item.source_path.startswith("spec.")
    }


def first_field(fields: set[str], *candidates: str) -> str:
    return next((item for item in candidates if item in fields), "")


def resource_function(resource: str) -> str:
    return "PVC" if resource == "PersistentVolumeClaim" else resource


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
