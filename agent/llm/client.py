"""OpenAI LLM client abstraction for Agent planners."""

from __future__ import annotations

import os
from dataclasses import dataclass


REQUIRED_ENV_MESSAGE = "LLM planner를 사용하려면 OPENAI_API_KEY와 OPENAI_MODEL 설정이 필요합니다."


class LLMUnavailable(RuntimeError):
    """Raised when the LLM planner cannot be used."""


@dataclass
class LLMConfig:
    model: str = "gpt-5.4-mini"


def config_from_env(model: str | None = None) -> LLMConfig:
    return LLMConfig(model=model or os.environ.get("OPENAI_MODEL", "gpt-5.4-mini"))


def chat_json(system_prompt: str, user_prompt: str, config: LLMConfig | None = None) -> str:
    cfg = config or config_from_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LLMUnavailable(REQUIRED_ENV_MESSAGE)

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise LLMUnavailable(
            "LLM planner를 사용하려면 langchain-openai, langchain, openai 패키지가 필요합니다. "
            "설치 예: pip install -r requirements.txt"
        ) from exc

    model = ChatOpenAI(model=cfg.model, temperature=0)
    response = model.invoke(
        [
            ("system", system_prompt),
            ("user", user_prompt),
        ]
    )
    content = getattr(response, "content", response)
    if not isinstance(content, str):
        content = str(content)
    return content
