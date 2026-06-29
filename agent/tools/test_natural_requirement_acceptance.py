"""Acceptance tests for beginner natural-language Operator requirements."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.context_builder import missing_information, summarize_requirement
from agent.tools.spec_generator import generate_spec


def generated(text: str) -> dict:
    return generate_spec(text, Path("requirements/acceptance.txt"))


def rbac(spec: dict, resource: str) -> list[str]:
    return next(
        item["verbs"]
        for item in spec["rbac"]["resources"]
        if item["resource"] == resource
    )


class NaturalRequirementAcceptanceTest(unittest.TestCase):
    def test_natural_deployment_management(self) -> None:
        text = """
AppService라는 Custom Resource를 만들고 싶습니다.
사용자가 컨테이너 이미지와 실행할 개수를 입력하면 Controller가 Deployment를 생성해주세요. 이미지나 실행 개수가 바뀌면 Deployment에도 반영되어야 합니다.
누군가 Deployment를 직접 수정하면 AppService에 입력된 값으로 다시 되돌려주세요.
현재 준비된 Pod 개수와 처리 상태, 오류 메시지는 AppService의 status에서 확인하고 싶습니다.
AppService가 삭제되면 생성된 Deployment도 함께 삭제해주세요.
API는 apps.sample.io/v1alpha1을 사용합니다.
"""
        spec = generated(text)
        self.assertEqual(spec["api"], {"domain": "sample.io", "group": "apps", "version": "v1alpha1", "kind": "AppService"})
        self.assertEqual([item["name"] for item in spec["specFields"]], ["image", "replicas"])
        self.assertEqual([item["name"] for item in spec["statusFields"]], ["readyReplicas", "phase", "message"])
        self.assertEqual(spec["controller"]["managedResources"], ["Deployment"])
        self.assertNotIn("Pod", spec["controller"]["managedResources"])
        self.assertEqual(spec["controller"]["resourcePolicies"][0]["deletionPolicy"], "garbage-collect")

    def test_deployment_and_service_are_distinct(self) -> None:
        spec = generated("""
WebApplication Operator를 만들고 싶습니다.
API는 platform.sample.io/v1alpha1입니다.
spec:
image: string
replicas: int32
containerPort: int32
servicePort: int32
status:
phase: string
readyReplicas: int32
serviceName: string
message: string
Controller는 Deployment와 Service를 생성해야 합니다.
Deployment에는 image, replicas, containerPort를 반영하고, Service는 해당 Deployment의 Pod를 선택해서 servicePort로 노출해야 합니다.
spec이 바뀌면 Deployment와 Service를 갱신하고, 외부에서 변경된 경우 원래 상태로 복구해주세요.
WebApplication이 삭제되면 Deployment와 Service도 함께 삭제해주세요.
""")
        self.assertEqual(spec["controller"]["managedResources"], ["Deployment", "Service"])
        self.assertNotIn("Pod", spec["controller"]["managedResources"])
        self.assertEqual(set(rbac(spec, "deployments")), {"get", "list", "watch", "create", "update", "patch", "delete"})
        self.assertEqual(set(rbac(spec, "services")), {"get", "list", "watch", "create", "update", "patch", "delete"})

    def test_configmap_map_type_and_drift(self) -> None:
        spec = generated("""
ApplicationConfig라는 Custom Resource를 만들고 싶습니다.
API는 config.sample.io/v1alpha1입니다.
사용자는 spec에 다음 값을 입력합니다.
configName: string
data: map[string]string
Controller는 ApplicationConfig의 내용을 기반으로 ConfigMap을 생성해야 합니다.
spec.data가 바뀌면 ConfigMap의 data도 변경하고, ConfigMap이 직접 수정되면 ApplicationConfig의 값으로 복구해주세요.
status에는 다음 내용을 표시해주세요.
phase: string
configMapName: string
message: string
ApplicationConfig를 삭제하면 ConfigMap도 삭제해주세요.
""")
        self.assertEqual(spec["controller"]["managedResources"], ["ConfigMap"])
        self.assertEqual(next(item["type"] for item in spec["specFields"] if item["name"] == "data"), "map[string]string")
        self.assertNotIn("Config", spec["controller"]["managedResources"])

    def test_read_only_deployment_contract(self) -> None:
        spec = generated("""
DeploymentHealth라는 Custom Resource를 만들고 싶습니다.
API는 monitoring.sample.io/v1alpha1입니다.
spec:
deploymentName: string
namespace: string
status:
phase: string
desiredReplicas: int32
readyReplicas: int32
message: string
Controller는 기존 Deployment를 생성하거나 수정하지 않습니다.
spec에 지정된 Deployment를 조회해서 desiredReplicas와 readyReplicas를 status에 기록해주세요.
Deployment가 없으면 NotFound 상태와 설명을 기록해주세요.
DeploymentHealth가 삭제되어도 기존 Deployment는 삭제하면 안 됩니다.
""")
        self.assertEqual(spec["controller"]["managedResources"], [])
        self.assertEqual(spec["controller"]["observedResources"], ["Deployment"])
        self.assertEqual(rbac(spec, "deployments"), ["get", "list", "watch"])
        policy = spec["controller"]["resourcePolicies"][0]
        self.assertEqual((policy["strategy"], policy["ownership"], policy["deletionPolicy"]), ("read-only", "none", "retain"))

    def test_missing_kind_requests_only_missing_information(self) -> None:
        text = """
이미지와 replicas 값을 받아서 Deployment를 생성하는 Operator를 만들고 싶습니다.
API는 apps.sample.io/v1alpha1을 사용하고 싶습니다.
status에서는 준비된 replicas 수와 처리 결과를 보고 싶습니다.
"""
        summary = summarize_requirement(text)
        missing = missing_information(summary, text)
        self.assertFalse(summary["kind"])
        self.assertEqual((summary["domain"], summary["group"], summary["version"]), ("sample.io", "apps", "v1alpha1"))
        self.assertIn("kind", missing)

    def test_missing_api_is_not_invented(self) -> None:
        text = """
BackupPolicy라는 Custom Resource를 만들고 싶습니다.
spec에는 schedule과 retentionDays를 입력합니다.
Controller는 BackupPolicy의 값을 ConfigMap으로 저장하고, 값이 바뀌면 ConfigMap을 갱신해주세요.
status에는 phase와 message를 표시해주세요.
"""
        summary = summarize_requirement(text)
        self.assertEqual(summary["kind"], "BackupPolicy")
        self.assertEqual(summary["specFields"], ["schedule", "retentionDays"])
        self.assertEqual(summary["statusFields"], ["phase", "message"])
        self.assertFalse(summary["domain"] or summary["group"] or summary["version"])
        self.assertEqual(
            missing_information(summary, text),
            ["domain", "group", "version"],
        )

    def test_untyped_named_fields_require_confirmation(self) -> None:
        text = """
WorkerPool이라는 Custom Resource를 만들고 싶습니다.
API는 compute.sample.io/v1alpha1입니다.
사용자는 workerImage, workerCount, queueName을 입력합니다.
Controller는 Deployment를 생성하고 workerImage와 workerCount를 반영합니다.
status에는 현재 실행 중인 worker 수와 상태 메시지를 표시합니다.
"""
        summary = summarize_requirement(text)
        self.assertEqual(summary["specFields"], ["workerImage", "workerCount", "queueName"])
        self.assertEqual(summary["ambiguousFieldTypes"], ["spec.workerImage", "spec.workerCount", "spec.queueName"])

    def test_appservice_does_not_imply_service(self) -> None:
        spec = generated("""
AppService라는 Custom Resource가 Deployment 하나를 관리하도록 만들어주세요.
API는 apps.sample.io/v1alpha1입니다.
spec:
image: string
replicas: int32
status:
readyReplicas: int32
phase: string
Controller가 생성하고 수정할 리소스는 Deployment뿐입니다.
Kubernetes Service는 생성하지 않습니다.
""")
        self.assertEqual(spec["controller"]["managedResources"], ["Deployment"])
        self.assertFalse(any(item["resource"] == "services" for item in spec["rbac"]["resources"]))

    def test_job_managed_and_pod_observed(self) -> None:
        spec = generated("""
BatchApplication Operator를 만들고 싶습니다.
API는 batch.sample.io/v1alpha1입니다.
Controller는 Job을 생성하고 관리해야 합니다.
Job이 생성한 Pod의 상태를 조회해서 성공 여부와 실패 메시지를 status에 기록해주세요.
Controller가 Pod를 직접 생성하거나 수정하거나 삭제하면 안 됩니다.
BatchApplication이 삭제되면 Job은 함께 삭제해주세요.
spec:
image: string
status:
phase: string
message: string
""")
        self.assertEqual(spec["controller"]["managedResources"], ["Job"])
        self.assertEqual(spec["controller"]["observedResources"], ["Pod"])
        self.assertEqual(rbac(spec, "pods"), ["get", "list", "watch"])
        self.assertIn("create", rbac(spec, "jobs"))

    def test_service_monitor_name_does_not_imply_service(self) -> None:
        spec = generated("""
ServiceMonitor라는 Custom Resource를 만들고 싶습니다.
API는 observability.sample.io/v1alpha1입니다.
이 Custom Resource는 Deployment 상태를 읽고, 결과를 ConfigMap에 기록해야 합니다.
Kubernetes Service는 만들거나 수정하지 않습니다.
spec:
deploymentName: string
outputConfigMapName: string
status:
phase: string
readyReplicas: int32
message: string
""")
        self.assertEqual(spec["controller"]["managedResources"], ["ConfigMap"])
        self.assertEqual(spec["controller"]["observedResources"], ["Deployment"])
        self.assertFalse(any(item["resource"] == "services" for item in spec["rbac"]["resources"]))

    def test_unknown_kind_is_kept_for_discovery(self) -> None:
        spec = generated("""
DataPipeline이라는 Custom Resource를 만들고 싶습니다.
API는 data.sample.io/v1alpha1입니다.
Controller는 example.io/v1alpha1의 MagicWorker 리소스를 생성하고 관리해야 합니다.
spec:
image: string
workers: int32
status:
phase: string
message: string
MagicWorker가 클러스터에 없으면 실행하지 말고 이유를 설명해주세요.
""")
        self.assertEqual(spec["controller"]["managedResources"], ["MagicWorker"])

    def test_wildcard_rbac_is_rejected(self) -> None:
        spec = generated("""
AdminApplication Operator를 만들고 싶습니다.
API는 admin.sample.io/v1alpha1입니다.
Controller는 ConfigMap 하나를 생성하고 관리합니다.
편의를 위해 모든 API Group과 모든 Resource에 대해 모든 권한을 부여해주세요.
spec:
configName: string
value: string
status:
phase: string
message: string
""")
        self.assertTrue(any("Wildcard RBAC" in item for item in spec["warnings"]))
        self.assertFalse(any("*" in item["verbs"] for item in spec["rbac"]["resources"]))

    def test_pvc_retain_and_immutable_policy(self) -> None:
        spec = generated("""
StorageClaim이라는 Custom Resource를 만들고 싶습니다.
API는 storage.sample.io/v1alpha1입니다.
spec:
storageClassName: string
size: string
accessMode: string
Controller는 PVC를 생성해야 합니다.
size가 증가하면 PVC 요청 용량을 갱신해주세요.
storageClassName이나 accessMode가 변경된 경우에는 무조건 patch하지 말고, 변경 불가능한 필드인지 확인해주세요.
StorageClaim이 삭제되더라도 데이터 보호를 위해 PVC는 자동 삭제하지 마세요.
status:
phase: string
pvcName: string
message: string
""")
        self.assertEqual(spec["controller"]["managedResources"], ["PVC"])
        policy = spec["controller"]["resourcePolicies"][0]
        self.assertEqual((policy["ownership"], policy["deletionPolicy"]), ("none", "retain"))

    def test_unknown_field_types_are_not_treated_as_go_types(self) -> None:
        text = """
InvalidExample이라는 Custom Resource를 만들고 싶습니다.
API는 invalid.sample.io/v1alpha1입니다.
spec:
count: 숫자 타입
options: 알 수 없는 사용자 정의 타입
status:
phase: string
Controller는 Deployment를 생성합니다.
"""
        spec = generated(text)
        self.assertTrue(any("Field type requires confirmation" in item for item in spec["errors"]))
        summary = summarize_requirement(text)
        self.assertEqual(summary["ambiguousFieldTypes"], ["spec.count", "spec.options"])


if __name__ == "__main__":
    unittest.main()
