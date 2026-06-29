"""Tests for requirement-to-spec generation."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.tools.spec_generator import (
    MAX_PROJECT_NAME_LENGTH,
    bounded_project_name,
    generate_spec,
    mapping_target_kind,
    parse_sample_defaults,
)


class SpecGeneratorTest(unittest.TestCase):
    def test_structured_english_headings_are_fully_parsed(self) -> None:
        spec = generate_spec(
            """
Operator Kind: AppService
API Domain: sample.io
API Group: apps
API Version: v1alpha1

Spec Fields:
- image: string
- replicas: int32
- port: int32

Status Fields:
- phase: string
- readyReplicas: int32
- message: string

Managed Resources:
- Deployment

Controller Responsibilities:
- AppService 생성 및 변경을 감지한다.
- Deployment를 생성하고 갱신한다.
- spec.image를 Deployment의 컨테이너 이미지에 반영한다.
- spec.replicas를 Deployment의 replicas에 반영한다.
- Deployment가 외부에서 변경되면 AppService spec 기준으로 복구한다.
- 실제 readyReplicas를 status.readyReplicas에 기록한다.
- AppService가 삭제되면 Deployment도 삭제한다.

Validation:
- make generate
- make manifests
- make test
""",
            Path("requirements/appservice-structured.txt"),
        )

        self.assertEqual(
            spec["api"],
            {
                "domain": "sample.io",
                "group": "apps",
                "version": "v1alpha1",
                "kind": "AppService",
            },
        )
        self.assertEqual(
            [(item["name"], item["type"]) for item in spec["specFields"]],
            [("image", "string"), ("replicas", "int32"), ("port", "int32")],
        )
        self.assertEqual(
            [(item["name"], item["type"]) for item in spec["statusFields"]],
            [("phase", "string"), ("readyReplicas", "int32"), ("message", "string")],
        )
        self.assertEqual(spec["controller"]["managedResources"], ["Deployment"])
        self.assertEqual(
            spec["validation"]["commands"],
            ["make generate", "make manifests", "make test"],
        )
        self.assertEqual(spec["errors"], [])

    def test_beginner_appservice_format_is_fully_parsed(self) -> None:
        spec = generate_spec(
            """
애플리케이션을 배포하고 관리하는 AppService Operator를 만들고 싶습니다.
Custom Resource 이름은 AppService로 하고, API는 apps.sample.io/v1alpha1을 사용합니다.

사용자가 spec에 다음 값을 입력할 수 있어야 합니다.
* image: 실행할 컨테이너 이미지
* replicas: 실행할 Pod 개수
* port: 컨테이너가 사용하는 포트

Controller는 AppService 리소스를 감지해서 Deployment를 생성하고 관리해야 합니다.
spec.image가 변경되면 Deployment의 컨테이너 이미지를 변경해야 합니다.

AppService의 status에는 다음 값을 표시해주세요.
* phase: 현재 처리 상태
* readyReplicas: 실제 준비된 Pod 개수
* message: 처리 결과 또는 오류 설명

AppService가 삭제되면 Controller가 생성한 Deployment도 함께 삭제되어야 합니다.
코드 생성 후 make generate, make manifests, make test를 실행해 검증해주세요.
""",
            Path("requirements/appservice.txt"),
        )

        self.assertEqual(
            spec["api"],
            {
                "domain": "sample.io",
                "group": "apps",
                "version": "v1alpha1",
                "kind": "AppService",
            },
        )
        self.assertEqual(
            [(item["name"], item["type"]) for item in spec["specFields"]],
            [("image", "string"), ("replicas", "int32"), ("port", "int32")],
        )
        self.assertEqual(
            [(item["name"], item["type"]) for item in spec["statusFields"]],
            [("phase", "string"), ("readyReplicas", "int32"), ("message", "string")],
        )
        self.assertEqual(spec["controller"]["managedResources"], ["Deployment"])
        self.assertEqual(spec["errors"], [])

    def test_requirement_sample_spec_is_parsed_without_profile(self) -> None:
        warnings: list[str] = []
        values = parse_sample_defaults(
            """
샘플 Custom Resource는 다음 값을 사용한다.
apiVersion: access.sample.io/v1alpha1
kind: AccessBundle
spec:
  ruleApiGroups: [""]
  ruleResources: [serviceaccounts]
  ruleVerbs: [get]
""",
            warnings,
        )

        self.assertEqual(
            values,
            {
                "ruleApiGroups": [""],
                "ruleResources": ["serviceaccounts"],
                "ruleVerbs": ["get"],
            },
        )
        self.assertEqual(warnings, [])

    def test_unknown_managed_kind_is_inferred_from_mapping_target(self) -> None:
        self.assertEqual(
            mapping_target_kind(
                "NetworkPolicy.spec.podSelector.matchLabels"
            ),
            "NetworkPolicy",
        )

    def test_short_project_name_keeps_readable_operator_suffix(
        self,
    ) -> None:
        self.assertEqual(
            bounded_project_name("WebService"),
            "web-service-operator",
        )

    def test_long_project_name_is_dns_safe_and_stable(self) -> None:
        first = bounded_project_name("NamespaceLabelPolicy")
        second = bounded_project_name("NamespaceLabelPolicy")

        self.assertEqual(first, second)
        self.assertLessEqual(len(first), MAX_PROJECT_NAME_LENGTH)
        self.assertRegex(first, r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
        self.assertIn("-op-", first)


if __name__ == "__main__":
    unittest.main()
