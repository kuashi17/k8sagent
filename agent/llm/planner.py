"""LLM planner functions for requirement planning and log analysis."""

from __future__ import annotations

import json
import re
from typing import Any

from agent.llm.client import LLMConfig, chat_json
from agent.llm.prompts import LOG_ANALYSIS_PLANNER_PROMPT, REQUIREMENT_PLANNER_PROMPT, SYSTEM_PROMPT


class LLMOutputParseError(ValueError):
    """Raised when a local LLM response cannot be parsed as JSON."""

    def __init__(self, message: str, raw_output: str):
        super().__init__(message)
        self.raw_output = raw_output


def plan_requirement_with_llm(
    requirement_text: str,
    retrieved_docs: list[dict[str, Any]],
    profile_summary: dict[str, Any],
    safety_mode: str,
    config: LLMConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    llm_input = {
        "mode": "requirement-planning",
        "requirementText": requirement_text,
        "retrievedDocs": retrieved_docs,
        "profileSummary": profile_summary,
        "safetyMode": safety_mode,
    }
    prompt = REQUIREMENT_PLANNER_PROMPT.format(
        requirement_text=requirement_text,
        retrieved_docs=json.dumps(retrieved_docs, ensure_ascii=False, indent=2),
        profile_summary=json.dumps(profile_summary, ensure_ascii=False, indent=2),
        safety_mode=safety_mode,
    )
    raw = chat_json(SYSTEM_PROMPT, prompt, config)
    return parse_json_object(raw), llm_input, raw


def analyze_log_with_llm(
    summary: dict[str, Any],
    analysis_md: str,
    retrieved_docs: list[dict[str, Any]],
    config: LLMConfig | None = None,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    llm_input = {
        "mode": "log-analysis",
        "summary": summary,
        "analysisMd": analysis_md,
        "retrievedDocs": retrieved_docs,
    }
    prompt = LOG_ANALYSIS_PLANNER_PROMPT.format(
        summary_json=json.dumps(summary, ensure_ascii=False, indent=2),
        analysis_md=analysis_md,
        retrieved_docs=json.dumps(retrieved_docs, ensure_ascii=False, indent=2),
    )
    raw = chat_json(SYSTEM_PROMPT, prompt, config)
    return parse_json_object(raw), llm_input, raw


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    candidates = [text]

    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if code_block:
        candidates.append(code_block.group(1).strip())

    first = text.find("{")
    last = text.rfind("}")
    if first != -1 and last != -1 and first < last:
        candidates.append(text[first : last + 1])

    data: Any = None
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            break
        except json.JSONDecodeError as exc:
            last_error = exc
    else:
        raise LLMOutputParseError(f"LLM output could not be parsed as JSON: {last_error}", raw)

    if not isinstance(data, dict):
        raise LLMOutputParseError("LLM output must be a JSON object.", raw)
    return data
