"""Typed Web request and beginner-facing result models."""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WebModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RequirementRunRequest(WebModel):
    requirement_text: str = Field(min_length=10)
    profile: str = ""
    mode: Literal["dry-run", "execute"] = "dry-run"
    run_level: Literal["fast", "standard"] = "fast"
    kind_deploy: bool = False
    resume_existing: bool = False
    confirm_execute: bool = False
    capability_proposal: str = ""
    capability_approval: str = ""
    confirm_capability: bool = False

    @model_validator(mode="after")
    def require_execute_confirmation(self) -> "RequirementRunRequest":
        if self.mode == "execute" and not self.confirm_execute:
            raise ValueError(
                "실제 생성을 시작하려면 실행 승인에 체크해 주세요."
            )
        has_capability_approval = bool(
            self.capability_proposal or self.capability_approval
        )
        if has_capability_approval and self.mode != "execute":
            raise ValueError(
                "Capability 계약 승인은 실제 생성 단계에서만 사용할 수 있습니다."
            )
        if has_capability_approval and not (
            self.capability_proposal
            and self.capability_approval
            and self.confirm_capability
        ):
            raise ValueError(
                "새 관리 리소스 지원 계약을 별도로 확인하고 승인해 주세요."
            )
        return self

    @classmethod
    def from_form(
        cls,
        form: Mapping[str, Any],
    ) -> "RequirementRunRequest":
        return cls.model_validate(
            {
                "requirement_text": str(
                    form.get("requirement_text") or ""
                ).strip(),
                "profile": str(form.get("profile") or "").strip(),
                "mode": str(form.get("mode") or "dry-run"),
                "run_level": str(form.get("run_level") or "fast"),
                "kind_deploy": checkbox(form.get("kind_deploy")),
                "resume_existing": checkbox(
                    form.get("resume_existing")
                ),
                "confirm_execute": checkbox(
                    form.get("confirm_execute")
                ),
                "capability_proposal": str(
                    form.get("capability_proposal") or ""
                ).strip(),
                "capability_approval": str(
                    form.get("capability_approval") or ""
                ).strip(),
                "confirm_capability": checkbox(
                    form.get("confirm_capability")
                ),
            }
        )


class LogAnalysisRequest(WebModel):
    log_dir: str = Field(min_length=1)

    @classmethod
    def from_form(
        cls,
        form: Mapping[str, Any],
    ) -> "LogAnalysisRequest":
        return cls(log_dir=str(form.get("log_dir") or "").strip())


class RunResultView(WebModel):
    state: str
    succeeded: bool
    title: str
    summary: str
    kind: str = ""
    managed_resources: list[str] = Field(default_factory=list)
    completed_steps: list[str] = Field(default_factory=list)
    failed_steps: list[str] = Field(default_factory=list)
    generated_artifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    can_execute: bool = False
    capability_proposal: str = ""
    capability_approval: str = ""
    capability_resources: list[str] = Field(default_factory=list)


def checkbox(value: Any) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}
