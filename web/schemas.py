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

    @model_validator(mode="after")
    def require_execute_confirmation(self) -> "RequirementRunRequest":
        if self.mode == "execute" and not self.confirm_execute:
            raise ValueError(
                "실제 생성을 시작하려면 실행 승인에 체크해 주세요."
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


def checkbox(value: Any) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}
