"""Validated Web workflow submission without UI rendering concerns."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from agent.tools.capability_drafter import load_proposal, proposal_digest
from web.schemas import LogAnalysisRequest, RequirementRunRequest


class WorkflowService:
    def __init__(
        self,
        repo_root: Path,
        log_root: Path,
    ) -> None:
        self.repo_root = repo_root
        self.log_root = log_root

    def submit_requirement(
        self,
        request: RequirementRunRequest,
        jobs: Any,
    ) -> dict[str, Any]:
        # Web 요청을 직접 처리하지 않고 Agent CLI 명령으로 변환한다.
        # 이렇게 해야 Web과 CLI가 같은 안전 정책, 같은 로그 형식, 같은 Tool 계약을 공유한다.
        if request.approval_parent_job_id:
            parent = jobs.get(request.approval_parent_job_id)
            parent_metadata = (parent or {}).get("metadata") or {}
            if (
                not parent
                or parent.get("state") != "succeeded"
                or parent.get("jobType") != "requirement"
                or parent_metadata.get("mode") != "dry-run"
            ):
                raise ValueError(
                    "승인 대기 시간을 연결할 완료된 계획 작업을 찾을 수 없습니다."
                )
            support = (
                (((parent.get("summary") or {}).get("agentResult") or {})
                .get("technicalDetails") or {})
                .get("capabilitySupport") or []
            )
            experimental = [
                str(item.get("resource") or "관리 리소스")
                for item in support
                if isinstance(item, dict)
                and item.get("level") == "experimental"
            ]
            if experimental and not request.confirm_experimental:
                raise ValueError(
                    "experimental 관리 기능의 제한사항을 확인하고 "
                    "별도 승인해 주세요: " + ", ".join(experimental)
                )
        if request.capability_proposal:
            self.validate_capability_approval(request, jobs)
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
                "mode": request.mode,
                "runLevel": request.run_level,
                "resumeExisting": request.resume_existing,
                "approvalParentJobId": request.approval_parent_job_id,
                "experimentalConfirmed": request.confirm_experimental,
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
                "agent/cli.py",
                "--analyze-log",
                self.relative(source),
            ],
            metadata={"sourceLogDir": self.relative(source)},
        )

    def submit_kind_validation(
        self,
        source_job_id: str,
        jobs: Any,
    ) -> dict[str, Any]:
        # kind 검증은 이미 코드 생성과 make 검증이 끝난 execute job에서만 시작한다.
        # 인프라 실패가 발생해도 원래 생성 결과를 덮어쓰지 않고 별도 job으로 기록한다.
        source = jobs.get(source_job_id)
        metadata = (source or {}).get("metadata") or {}
        if (
            not source
            or source.get("state") != "succeeded"
            or source.get("jobType") != "requirement"
            or metadata.get("mode") != "execute"
        ):
            raise ValueError(
                "코드 생성과 검증을 완료한 작업만 Kubernetes에서 검증할 수 있습니다."
            )
        requirement = self.resolve_repo_path(
            str(metadata.get("requirementPath") or "")
        )
        if not requirement.is_file():
            raise ValueError("원본 요구사항 파일을 찾을 수 없습니다.")
        for existing in jobs.list(100):
            existing_metadata = existing.get("metadata") or {}
            if (
                existing.get("jobType") == "kind-validation"
                and existing_metadata.get("sourceJobId") == source_job_id
                and existing.get("state")
                in {"queued", "running", "succeeded"}
            ):
                return existing
        return jobs.submit(
            "kind-validation",
            [
                "python3",
                "agent/evaluation/kind_matrix_runner.py",
                "--requirement",
                self.relative(requirement),
            ],
            metadata={
                "sourceJobId": source_job_id,
                "requirementPath": self.relative(requirement),
            },
        )

    def build_requirement_command(
        self,
        request: RequirementRunRequest,
        requirement_path: Path,
    ) -> list[str]:
        command = [
            "python3",
            "agent/cli.py",
            "--requirement",
            self.relative(requirement_path),
            "--mode",
            request.mode,
            "--run-level",
            request.run_level,
        ]
        if request.mode == "execute":
            command.append("--execute")
        if request.capability_proposal:
            command.extend(
                [
                    "--capability-proposal",
                    request.capability_proposal,
                    "--capability-approval",
                    request.capability_approval,
                ]
            )
        if request.resume_existing:
            command.append("--resume-existing")
        return command

    def validate_capability_approval(
        self,
        request: RequirementRunRequest,
        jobs: Any | None = None,
    ) -> None:
        path = self.resolve_repo_path(request.capability_proposal)
        allowed_roots = [(self.repo_root / "generated").resolve()]
        if jobs is not None and request.approval_parent_job_id:
            parent = jobs.get(request.approval_parent_job_id)
            parent_job_dir = str((parent or {}).get("jobDir") or "")
            if parent_job_dir:
                allowed_roots.append(
                    (self.repo_root / parent_job_dir / "artifacts").resolve()
                )
        if not any(is_relative_to(path, root) for root in allowed_roots):
            raise ValueError(
                "Capability 제안은 해당 계획 작업의 산출물만 승인할 수 있습니다."
            )
        if not path.is_file():
            raise ValueError("승인할 capability 제안 파일을 찾을 수 없습니다.")
        proposal = load_proposal(path)
        if proposal.proposalId != request.capability_approval:
            raise ValueError("검토한 capability 제안과 승인 값이 일치하지 않습니다.")
        if proposal.proposalId != proposal_digest(proposal):
            raise ValueError("Capability 제안 내용이 검토 후 변경되었습니다.")
        if proposal.status != "pending-approval" or proposal.approved:
            raise ValueError("대기 중인 capability 제안만 승인할 수 있습니다.")

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


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
