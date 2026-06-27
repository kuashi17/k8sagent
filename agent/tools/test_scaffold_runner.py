"""Tests for optimized scaffold generation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.tools.scaffold_runner import build_steps, patch_dockerfile


class ScaffoldRunnerTest(unittest.TestCase):
    def test_compile_pipeline_can_skip_duplicate_scaffold_validation(self) -> None:
        model = {
            "project": {"domain": "example.io", "module": "example.io/widget"},
            "api": {"group": "apps", "version": "v1", "kind": "Widget"},
            "controllerEnabled": True,
        }

        steps = build_steps(
            model,
            Path("/tmp/widget"),
            include_validation=False,
        )

        self.assertNotIn(
            "make-test",
            [step["name"] for step in steps],
        )
        self.assertIn(
            "kubebuilder-create-api",
            [step["name"] for step in steps],
        )

    def test_dockerfile_uses_shared_buildkit_go_caches(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Dockerfile"
            path.write_text(
                "RUN go mod download\n"
                "RUN CGO_ENABLED=0 GOOS=${TARGETOS:-linux} "
                "GOARCH=${TARGETARCH} go build -a -o manager cmd/main.go\n",
                encoding="utf-8",
            )

            patch_dockerfile(path)
            rendered = path.read_text(encoding="utf-8")

        self.assertIn("--mount=type=cache,target=/go/pkg/mod", rendered)
        self.assertIn("target=/root/.cache/go-build", rendered)
        self.assertNotIn("go build -a", rendered)


if __name__ == "__main__":
    unittest.main()
