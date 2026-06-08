"""LLM client abstraction for Agent planners."""

from __future__ import annotations

import os
import json
import urllib.error
import urllib.request
from dataclasses import dataclass


class LLMUnavailable(RuntimeError):
    """Raised when the requested LLM provider cannot be used."""


@dataclass
class LLMConfig:
    provider: str = "openai"
    model: str = "gpt-4.1-mini"
    base_url: str = ""


def config_from_env(provider: str | None = None, model: str | None = None) -> LLMConfig:
    selected_provider = provider or os.environ.get("LLM_PROVIDER", "openai")
    default_model = "llama3.1" if selected_provider == "local" else "gpt-4.1-mini"
    return LLMConfig(
        provider=selected_provider,
        model=model or os.environ.get("LOCAL_LLM_MODEL" if selected_provider == "local" else "OPENAI_MODEL", default_model),
        base_url=os.environ.get("LOCAL_LLM_BASE_URL", "http://localhost:11434"),
    )


def chat_json(system_prompt: str, user_prompt: str, config: LLMConfig | None = None) -> str:
    cfg = config or config_from_env()
    if cfg.provider == "disabled":
        raise LLMUnavailable("LLM provider is disabled. Use --planner mock or set a usable provider.")
    if cfg.provider == "local":
        return chat_json_ollama(system_prompt, user_prompt, cfg)
    if cfg.provider != "openai":
        raise LLMUnavailable(f"Unsupported LLM provider: {cfg.provider}")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LLMUnavailable(
            "OPENAI_API_KEY is not set, so the LLM planner cannot be used. "
            "Use --planner mock, or export OPENAI_API_KEY and optionally OPENAI_MODEL."
        )

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise LLMUnavailable(
            "langchain-openai is not installed. Install dependencies with "
            "`pip install langchain langchain-openai openai pydantic`, or use --planner mock."
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


def chat_json_ollama(system_prompt: str, user_prompt: str, config: LLMConfig) -> str:
    """Call a local Ollama-compatible chat API.

    Ollama is used as the first local open model target because it has a small
    HTTP API and supports JSON mode for recent models.
    """

    endpoint = f"{config.base_url.rstrip('/')}/api/chat"
    payload = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "format": "json",
        "stream": False,
        "options": {
            "temperature": 0,
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise LLMUnavailable(
            f"Local LLM provider is not reachable at {config.base_url}. "
            "Start Ollama with `ollama serve`, pull a model such as `ollama pull llama3.1`, "
            "or use --planner mock."
        ) from exc
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"Local LLM provider returned invalid JSON: {exc}") from exc

    message = data.get("message") or {}
    content = message.get("content")
    if not content:
        raise LLMUnavailable(f"Local LLM provider returned no message content: {data}")
    return str(content)
