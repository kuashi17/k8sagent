"""Validated Web workflow submission without UI rendering concerns."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from web.schemas import LogAnalysisRequest, RequirementRunRequest


class WorkflowService:
    def __init__(
        self,
        repo_root: Path,
        log_root: Path,
        profile_dir: Path,
    ) -> None:
        self.repo_root = repo_root
        self.log_root = log_root
        self.profile_dir = profile_dir

    def submit_requirement(
        self,
        request: RequirementRunRequest,
        jobs: Any,
    ) -> dict[str, Any]:
        profile = self.validate_profile(request.profile)
        if request.kind_deploy and not profile:
            raise ValueError(
                "kind 배포는 배포 설정이 있는 Profile을 먼저 선택해야 합니다."
            )
        if request.kind_deploy:
            data = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
            if not (data.get("kindDeployment") or {}).get("enabled"):
                raise ValueError(
                    "선택한 Profile은 kind 배포를 지원하지 않습니다."
                )

        run_dir = self.make_run_dir("requirement")
        requirement_path = run_dir / "requirement.txt"
        requirement_path.write_text(
            request.requirement_text,
            encoding="utf-8",
        )
        command = self.build_requirement_command(
            request,
            requirement_path,
        )
        return jobs.submit(
            "requirement",
            command,
            metadata={
                "requirementPath": self.relative(requirement_path),
                "profile": request.profile,
                "mode": request.mode,
                "runLevel": request.run_level,
                "kindDeploy": request.kind_deploy,
                "resumeExisting": request.resume_existing,
            },
        )

    def submit_log_analysis(
        self,
        request: LogAnalysisRequest,
        jobs: Any,
    ) -> dict[str, Any]:
        source = self.resolve_repo_path(request.log_dir)
        if not (source / "summary.json").is_file():
            raise ValueError(
                "선택한 로그 폴더에 summary.json이 없습니다."
            )
        return jobs.submit(
            "log-analysis",
            [
                "python3",
                "agent/langchain_agent.py",
                "--analyze-log",
                self.relative(source),
            ],
            metadata={"sourceLogDir": self.relative(source)},
        )

    def build_requirement_command(
        self,
        request: RequirementRunRequest,
        requirement_path: Path,
    ) -> list[str]:
        command = [
            "python3",
            "agent/langchain_agent.py",
            "--requirement",
            self.relative(requirement_path),
            "--mode",
            request.mode,
            "--run-level",
            request.run_level,
        ]
        if request.profile:
            command.extend(["--profile", request.profile])
        if request.mode == "execute":
            command.append("--execute")
        if request.kind_deploy:
            command.append("--kind-deploy")
        if request.resume_existing:
            command.append("--resume-existing")
        return command

    def validate_profile(self, value: str) -> Path | None:
        if not value:
            return None
        path = self.resolve_repo_path(value)
        try:
            path.relative_to(self.profile_dir.resolve())
        except ValueError as exc:
            raise ValueError(
                "Profile은 저장소의 profiles 폴더에서만 선택할 수 있습니다."
            ) from exc
        if not path.is_file() or path.suffix not in {".yaml", ".yml"}:
            raise ValueError("선택한 Profile 파일을 찾을 수 없습니다.")
        return path

    def resolve_repo_path(self, value: str) -> Path:
        candidate = Path(value)
        path = (
            candidate.resolve()
            if candidate.is_absolute()
            else (self.repo_root / candidate).resolve()
        )
        try:
            path.relative_to(self.repo_root.resolve())
        except ValueError as exc:
            raise ValueError(
                "저장소 밖의 경로는 사용할 수 없습니다."
            ) from exc
        return path

    def make_run_dir(self, kind: str) -> Path:
        run_dir = (
            self.log_root
            / kind
            / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        )
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.repo_root.resolve()))
