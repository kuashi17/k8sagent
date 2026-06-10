"""Prompts for LLM based Agent planning."""

from __future__ import annotations


SYSTEM_PROMPT = """\
You are an AI Agent that helps developers build Kubebuilder based Kubernetes Operators.

Principles:
- Convert natural language requirements into clear Operator development plans.
- Identify missing information explicitly.
- Use retrieved RAG documents as evidence. If something is not in the documents, mark it as an inference.
- Explain which retrieved document supports each important decision.
- Create executable Tool call plans, but do not execute tools yourself.
- For safety, if execute is not explicitly allowed, scaffold, patch, and e2e tools must stay in dry-run mode.
- Return JSON only. Do not wrap JSON in Markdown.
"""


REQUIREMENT_PLANNER_PROMPT = """\
Create a requirement planning JSON object.

Required JSON shape:
{{
  "requirementSummary": "...",
  "missingInformation": [],
  "recommendedProfile": "...",
  "reasoning": [
    "Decision or inference grounded in the requirement and retrieved documents."
  ],
  "ragEvidence": [
    {{
      "documentPath": "knowledge-base/...",
      "title": "...",
      "usedFor": "What decision this document supports.",
      "evidenceType": "retrieved | inference"
    }}
  ],
  "plannedSteps": [],
  "toolCalls": [
    {{"tool": "spec_generator", "mode": "generate", "reason": "..."}},
    {{"tool": "command_planner", "mode": "dry-run", "reason": "..."}},
    {{"tool": "scaffold_runner", "mode": "dry-run", "reason": "..."}}
  ],
  "risks": [],
  "nextActions": []
}}

Context:
Requirement text:
{requirement_text}

Retrieved knowledge docs:
{retrieved_docs}

Profile summary:
{profile_summary}

Safety mode:
{safety_mode}
"""


LOG_ANALYSIS_PLANNER_PROMPT = """\
Create a log analysis JSON object.

Required JSON shape:
{{
  "decision": "succeeded | failed | succeeded-with-warning",
  "classification": "...",
  "rootCause": "...",
  "evidence": [],
  "ragEvidence": [
    {{
      "documentPath": "knowledge-base/...",
      "title": "...",
      "usedFor": "What troubleshooting judgment this document supports.",
      "evidenceType": "retrieved | inference"
    }}
  ],
  "recommendedFixes": [],
  "rerunCommand": "...",
  "explanationForBeginner": "..."
}}

Context:
summary.json:
{summary_json}

analysis.md:
{analysis_md}

Retrieved troubleshooting docs:
{retrieved_docs}
"""
