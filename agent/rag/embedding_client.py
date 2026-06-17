#!/usr/bin/env python3
"""Ollama local embedding client."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"


class EmbeddingUnavailable(RuntimeError):
    """Raised when the local embedding model cannot be used."""


@dataclass
class EmbeddingConfig:
    base_url: str = DEFAULT_OLLAMA_BASE_URL
    model: str = DEFAULT_EMBEDDING_MODEL
    timeout_seconds: int = 60
    retries: int = 2


def config_from_env() -> EmbeddingConfig:
    timeout = parse_int(os.environ.get("LOCAL_EMBEDDING_TIMEOUT_SECONDS"), 60)
    retries = parse_int(os.environ.get("LOCAL_EMBEDDING_RETRIES"), 2)
    return EmbeddingConfig(
        base_url=os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL),
        model=os.environ.get("LOCAL_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        timeout_seconds=timeout,
        retries=retries,
    )


def embed_text(text: str, config: EmbeddingConfig | None = None) -> list[float]:
    cfg = config or config_from_env()
    payload = {"model": cfg.model, "prompt": text}
    endpoint = f"{cfg.base_url.rstrip('/')}/api/embeddings"
    last_error: Exception | None = None
    for attempt in range(cfg.retries + 1):
        try:
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=cfg.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            embedding = data.get("embedding")
            if not isinstance(embedding, list) or not embedding:
                raise EmbeddingUnavailable(f"Ollama embedding response did not include an embedding: {data}")
            return [float(value) for value in embedding]
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, EmbeddingUnavailable) as exc:
            last_error = exc
            if attempt < cfg.retries:
                time.sleep(0.5 * (attempt + 1))
                continue
    raise EmbeddingUnavailable(connection_error_message(cfg, last_error))


def embed_texts(texts: list[str], config: EmbeddingConfig | None = None) -> list[list[float]]:
    cfg = config or config_from_env()
    return [embed_text(text, cfg) for text in texts]


def check_embedding_model(config: EmbeddingConfig | None = None) -> dict[str, Any]:
    cfg = config or config_from_env()
    embedding = embed_text("embedding health check", cfg)
    return {"baseUrl": cfg.base_url, "model": cfg.model, "dimension": len(embedding)}


def connection_error_message(cfg: EmbeddingConfig, error: Exception | None) -> str:
    return (
        "Ollama embedding endpoint에 연결할 수 없거나 embedding model을 사용할 수 없습니다. "
        f"`ollama serve`와 `ollama pull {cfg.model}`을 먼저 확인하세요. "
        f"현재 OLLAMA_BASE_URL={cfg.base_url}, LOCAL_EMBEDDING_MODEL={cfg.model}. "
        f"원인: {error}"
    )


def parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
