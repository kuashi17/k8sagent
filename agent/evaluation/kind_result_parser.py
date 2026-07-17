"""Helpers for extracting structured results from kind runner output."""

from __future__ import annotations

import json
from typing import Any


def parse_summary(stdout: str) -> dict[str, Any]:
    """Return the final lifecycle summary embedded in mixed progress output.

    kind 실행 중에는 진행 메시지와 JSON이 함께 출력될 수 있다. 화면 문구를
    추측하지 않고 `status`와 `checks`를 가진 구조화 결과를 최종 근거로 선택한다.
    """

    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    for index, character in enumerate(stdout):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            objects.append(value)
    summaries = [
        item for item in objects if "status" in item and "checks" in item
    ]
    if summaries:
        return summaries[-1]
    return objects[0] if objects else {}
