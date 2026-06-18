"""Ollama local LLM client for Agent planners."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit


DEFAULT_LOCAL_LLM_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LOCAL_LLM_MODEL = "qwen2.5-coder:3b"


class LLMUnavailable(RuntimeError):
    """Raised when the local LLM provider cannot be used."""


@dataclass
class LLMConfig:
    base_url: str = DEFAULT_LOCAL_LLM_BASE_URL
    model: str = DEFAULT_LOCAL_LLM_MODEL
    timeout_seconds: int = 180
    max_tokens: int = 800
    keep_alive: str = "30m"


def config_from_env(model: str | None = None) -> LLMConfig:
    timeout = os.environ.get("LOCAL_LLM_TIMEOUT_SECONDS", "180")
    try:
        timeout_seconds = int(timeout)
    except ValueError:
        timeout_seconds = 180
    max_tokens_raw = os.environ.get("LOCAL_LLM_MAX_TOKENS", "700")
    try:
        max_tokens = int(max_tokens_raw)
    except ValueError:
        max_tokens = 700
    return LLMConfig(
        base_url=os.environ.get("LOCAL_LLM_BASE_URL", DEFAULT_LOCAL_LLM_BASE_URL),
        model=model or os.environ.get("LOCAL_LLM_MODEL", DEFAULT_LOCAL_LLM_MODEL),
        timeout_seconds=timeout_seconds,
        max_tokens=max_tokens,
        keep_alive=os.environ.get("LOCAL_LLM_KEEP_ALIVE", "30m"),
    )


def chat_json(system_prompt: str, user_prompt: str, config: LLMConfig | None = None) -> str:
    cfg = config or config_from_env()
    endpoint = f"{request_base_url(cfg.base_url).rstrip('/')}/chat/completions"
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "max_tokens": cfg.max_tokens,
        "keep_alive": cfg.keep_alive,
        "options": {
            "num_predict": cfg.max_tokens,
            "temperature": 0,
        },
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
        raise LLMUnavailable(f"{local_connection_error(cfg)} 요청이 {cfg.timeout_seconds}초 안에 끝나지 않았습니다.") from exc
    except json.JSONDecodeError as exc:
        raise LLMUnavailable(f"Ollama local LLM endpoint returned invalid JSON: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMUnavailable(f"Ollama local LLM endpoint returned an unexpected response shape: {data}") from exc
    if not content:
        raise LLMUnavailable(f"Ollama local LLM endpoint returned an empty response for model {cfg.model}.")
    return str(content)


def warm_up_model(config: LLMConfig | None = None) -> bool:
    """Load the configured Ollama model without generating planning output."""

    cfg = config or config_from_env()
    parsed = urlsplit(request_base_url(cfg.base_url))
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, "/api/generate", "", ""))
    payload = {
        "model": cfg.model,
        "prompt": "",
        "stream": False,
        "keep_alive": cfg.keep_alive,
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=cfg.timeout_seconds) as response:
            json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LLMUnavailable(f"Local LLM warm-up failed for model {cfg.model}: {exc}") from exc
    return True


def local_connection_error(cfg: LLMConfig) -> str:
    return (
        "Ollama local LLM endpoint에 연결할 수 없습니다. "
        f"먼저 `ollama serve` 또는 `ollama run {cfg.model}`을 실행하세요. "
        f"현재 LOCAL_LLM_BASE_URL={cfg.base_url}, LOCAL_LLM_MODEL={cfg.model}"
    )


def request_base_url(base_url: str) -> str:
    """Use IPv4 loopback for localhost to avoid WSL IPv6 connection-refused cases."""

    parsed = urlsplit(base_url)
    if parsed.hostname != "localhost":
        return base_url
    netloc = "127.0.0.1"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
