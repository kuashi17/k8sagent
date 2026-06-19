"""Render profile-less Controller behavior from a generalized Operator spec."""

from __future__ import annotations

from typing import Any


RESOURCE_META = {
    "ConfigMap": ("", "v1", "ConfigMap", "config"),
    "Secret": ("", "v1", "Secret", "secret"),
    "PVC": ("", "v1", "PersistentVolumeClaim", "pvc"),
    "PersistentVolumeClaim": (
        "",
        "v1",
        "PersistentVolumeClaim",
        "pvc",
    ),
    "CronJob": ("batch", "v1", "CronJob", "cronjob"),
    "Deployment": ("apps", "v1", "Deployment", "deployment"),
    "Service": ("", "v1", "Service", "service"),
    "Namespace": ("", "v1", "Namespace", "namespace"),
}


def render_controller(model: dict[str, Any]) -> str:
    api = model["api"]
    project = model["project"]
    kind = api["kind"]
    alias = api_alias(api["group"], api["version"])
    resources = supported_resources(
        (model.get("controller") or {}).get("managedResources") or []
    )
    if not resources:
        raise SystemExit(
            "profile-less controller generation requires at least one "
            "supported managed resource"
        )

    reconcile_calls = []
    functions = []
    for resource in resources:
        key = RESOURCE_META[resource][3]
        reconcile_calls.append(
            f'\t{key}Name, err := r.reconcile{resource_function(resource)}'
            f"(ctx, &instance)\n"
            "\tif err != nil {\n"
            f'\t\t_ = r.updateStatus(ctx, &instance, "Error", err.Error(), names)\n'
            "\t\treturn ctrl.Result{}, err\n"
            "\t}\n"
            f'\tnames["{resource}"] = {key}Name'
        )
        functions.append(render_resource_function(resource, model, alias))

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

\t{alias} "{project["module"]}/api/{api["version"]}"
)

type {kind}Reconciler struct {{
\tclient.Client
\tScheme *runtime.Scheme
}}

{render_marker_block(model)}

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
{render_status_function(model, alias)}

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
    resource: str,
    model: dict[str, Any],
    alias: str,
) -> str:
    api = model["api"]
    kind = api["kind"]
    group, version, object_kind, suffix = RESOURCE_META[resource]
    function_name = resource_function(resource)
    name_expression = resource_name_expression(resource, model)
    namespace = '""' if resource == "Namespace" else "instance.Namespace"
    mutations = render_mutations(resource, model)
    disable_guard = render_disable_guard(
        resource,
        model,
        namespace,
    )
    owner = (
        ""
        if resource == "Namespace"
        else "\t\treturn setOwner(instance, object, r.Scheme)\n"
    )
    final_return = "\t\treturn nil\n" if resource == "Namespace" else owner
    return f'''func (r *{kind}Reconciler) reconcile{function_name}(ctx context.Context, instance *{alias}.{kind}) (string, error) {{
\tname := {name_expression}
\tif name == "" {{
\t\tname = instance.Name + "-{suffix}"
\t}}
\tobject := managedObject("{group}", "{version}", "{object_kind}", {namespace}, name)
{disable_guard}
\t_, err := controllerutil.CreateOrUpdate(ctx, r.Client, object, func() error {{
\t\tlabels := object.GetLabels()
\t\tif labels == nil {{
\t\t\tlabels = map[string]string{{}}
\t\t}}
\t\tlabels["app.kubernetes.io/managed-by"] = "{api["kind"].lower()}-operator"
\t\tlabels["operator.sample.io/owner"] = instance.Name
\t\tobject.SetLabels(labels)
{mutations}
{final_return}\t}})
\tif err != nil {{
\t\treturn name, fmt.Errorf("reconcile {object_kind}: %w", err)
\t}}
\treturn name, nil
}}
'''


def render_mutations(resource: str, model: dict[str, Any]) -> str:
    fields = field_names(model)
    lines: list[str] = []
    if resource == "ConfigMap":
        source = first_field(fields, "configData", "data")
        if source:
            lines.append(
                f'\t\tif err := unstructured.SetNestedStringMap(object.Object, '
                f"copyStringMap(instance.Spec.{go_name(source)}), \"data\"); err != nil {{ return err }}"
            )
    elif resource == "Secret":
        source = first_field(fields, "data", "secretData")
        if source:
            lines.append(
                f'\t\tif err := unstructured.SetNestedStringMap(object.Object, '
                f"copyStringMap(instance.Spec.{go_name(source)}), \"stringData\"); err != nil {{ return err }}"
            )
    elif resource in {"PVC", "PersistentVolumeClaim"}:
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
    elif resource == "CronJob":
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
    elif resource == "Deployment":
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
    elif resource == "Service":
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
    elif resource == "Namespace":
        labels = first_field(fields, "labels")
        if labels:
            lines.append(
                f"\t\tfor key, value := range instance.Spec.{go_name(labels)} {{ labels[key] = value }}\n"
                "\t\tobject.SetLabels(labels)"
            )
    return "\n".join(lines)


def render_disable_guard(
    resource: str,
    model: dict[str, Any],
    namespace: str,
) -> str:
    fields = field_names(model)
    if resource not in {"ConfigMap", "Secret"} or "enabled" not in fields:
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


def render_status_function(model: dict[str, Any], alias: str) -> str:
    kind = model["api"]["kind"]
    status_fields = {
        str(item.get("name"))
        for item in model.get("statusFields") or []
        if isinstance(item, dict)
    }
    assignments = []
    if "phase" in status_fields:
        assignments.append("\tinstance.Status.Phase = phase")
    if "message" in status_fields:
        assignments.append("\tinstance.Status.Message = message")
    mappings = {
        "configMapName": "ConfigMap",
        "secretName": "Secret",
        "claimName": "PVC",
        "cronJobName": "CronJob",
        "deploymentName": "Deployment",
        "serviceName": "Service",
        "observedNamespace": "Namespace",
    }
    for field, resource in mappings.items():
        if field in status_fields:
            assignments.append(
                f'\tinstance.Status.{go_name(field)} = names["{resource}"]'
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


def render_marker_block(model: dict[str, Any]) -> str:
    lines = []
    for item in model.get("rbacResources") or []:
        group = item.get("apiGroup", "")
        group_value = '""' if group == "" else group
        verbs = ";".join(item.get("verbs") or [])
        lines.append(
            f"// +kubebuilder:rbac:groups={group_value},"
            f"resources={item.get('resource')},verbs={verbs}"
        )
    return "\n".join(lines)


def resource_name_expression(resource: str, model: dict[str, Any]) -> str:
    fields = field_names(model)
    candidates = {
        "ConfigMap": ("configMapName", "name"),
        "Secret": ("secretName", "targetName", "name"),
        "PVC": ("claimName", "pvcName"),
        "PersistentVolumeClaim": ("claimName", "pvcName"),
        "CronJob": ("cronJobName",),
        "Deployment": ("deploymentName", "appName"),
        "Service": ("serviceName", "appName"),
        "Namespace": ("namespaceName",),
    }[resource]
    field = first_field(fields, *candidates)
    return f"instance.Spec.{go_name(field)}" if field else '""'


def supported_resources(resources: list[Any]) -> list[str]:
    result = []
    for value in resources:
        name = str(value)
        if name in RESOURCE_META and name not in result:
            result.append(name)
    return result


def field_names(model: dict[str, Any]) -> set[str]:
    return {
        str(item.get("name"))
        for item in model.get("specFields") or []
        if isinstance(item, dict) and item.get("name")
    }


def first_field(fields: set[str], *candidates: str) -> str:
    return next((item for item in candidates if item in fields), "")


def resource_function(resource: str) -> str:
    return "PVC" if resource == "PersistentVolumeClaim" else resource


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
