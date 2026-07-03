from __future__ import annotations

import unittest
from pathlib import Path

from agent.evaluation.response_consistency_runner import (
    canonical_contract,
    compare_expected,
    run_matrix,
)


class ResponseConsistencyRunnerTest(unittest.TestCase):
    def test_forbidden_rbac_is_checked(self) -> None:
        actual = {"rbac": {"pods": ["get", "create"]}}
        failures = compare_expected(actual, {"forbiddenRbac": {"pods": ["create", "delete"]}})
        self.assertEqual(failures[0]["actual"], ["create"])

    def test_contract_separates_managed_and_observed_resources(self) -> None:
        contract = canonical_contract(
            """
BatchApplication Operator를 만들고 싶습니다.
API는 batch.sample.io/v1alpha1입니다.
Controller는 Job을 생성하고 관리하며 Job의 Pod는 상태만 조회합니다.
Pod를 직접 생성하거나 수정하거나 삭제하면 안 됩니다.
spec:\nimage: string
status:\nphase: string
""",
            Path("requirements/test.txt"),
        )
        self.assertEqual(contract["managedResources"], ["Job"])
        self.assertEqual(contract["observedResources"], ["Pod"])
        self.assertEqual(contract["rbac"]["pods"], ["get", "list", "watch"])

    def test_default_golden_matrix_passes(self) -> None:
        matrix = Path("evaluation/fixtures/response-consistency-matrix.yaml")
        result = run_matrix(matrix, 3)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["summary"]["cases"], 20)
        self.assertEqual(result["summary"]["consistentCases"], 20)
        self.assertEqual(result["summary"]["equivalentGroups"], 1)


if __name__ == "__main__":
    unittest.main()
