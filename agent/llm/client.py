"""Ollama local LLM client for Agent planners."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


DEFAULT_LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LOCAL_LLM_MODEL = "qwen2.5-coder:7b"


class LLMUnavailable(RuntimeError):
    """Raised when the local LLM provider cannot be used."""


@dataclass
class LLMConfig:
    base_url: str = DEFAULT_LOCAL_LLM_BASE_URL
    model: str = DEFAULT_LOCAL_LLM_MODEL
    timeout_seconds: int = 180


def config_from_env(model: str | None = None) -> LLMConfig:
    timeout = os.environ.get("LOCAL_LLM_TIMEOUT_SECONDS", "180")
    try:
        timeout_seconds = int(timeout)
    except ValueError:
        timeout_seconds = 180
    return LLMConfig(
        base_url=os.environ.get("LOCAL_LLM_BASE_URL", DEFAULT_LOCAL_LLM_BASE_URL),
        model=model or os.environ.get("LOCAL_LLM_MODEL", DEFAULT_LOCAL_LLM_MODEL),
        timeout_seconds=timeout_seconds,
    )


def chat_json(system_prompt: str, user_prompt: str, config: LLMConfig | None = None) -> str:
    cfg = config or config_from_env()
    endpoint = f"{cfg.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer ollama",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise LLMUnavailable(f"{local_connection_error(cfg)} HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise LLMUnavailable(local_connection_error(cfg)) from exc
    except TimeoutError as exc:
        raise LLMUnavailable(local_connection_error(cfg)) from exc
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"Ollama local LLM endpoint returned invalid JSON: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable(f"Ollama local LLM endpoint returned an unexpected response shape: {data}") from exc
    if not content:
        raise LLMUnavailable(f"Ollama local LLM endpoint returned an empty response for model {cfg.model}.")
    return str(content)


def local_connection_error(cfg: LLMConfig) -> str:
    return (
        "Ollama local LLM endpoint에 연결할 수 없습니다. "
        f"먼저 `ollama serve` 또는 `ollama run {cfg.model}`을 실행하세요. "
        f"현재 LOCAL_LLM_BASE_URL={cfg.base_url}, LOCAL_LLM_MODEL={cfg.model}"
    )
