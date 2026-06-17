"""Prompts for LLM based Agent planning."""

from __future__ import annotations


SYSTEM_PROMPT = """\
You are an AI Agent that helps developers build Kubebuilder based Kubernetes Operators.

Principles:
- Convert natural language requirements into clear Operator development plans.
- Identify missing information explicitly.
- Use retrieved RAG documents as evidence. If something is not in the documents, mark it as an inference.
- Explain which retrieved document supports each important decision.
- Treat profiles as optional hints or examples, not as fixed product templates.
- Plan from the current user requirement first. Do not force AppConfig, TrainingJob, RedisCache, or any example profile when the requirement does not ask for it.
- Create executable Tool call plans, but do not execute tools yourself.
- For safety, if execute is not explicitly allowed, scaffold, patch, and e2e tools must stay in dry-run mode.
- Return JSON only. Do not wrap JSON in Markdown.
"""


REQUIREMENT_PLANNER_PROMPT = """\
Create a requirement planning JSON object.

Keep the response compact:
- requirementSummary: one sentence.
- missingInformation: max 6 items.
- reasoning: max 2 bullets.
- ragEvidence: max 3 items.
- plannedSteps: max 4 items.
- toolCalls: use only needed allowlisted tools.
- risks: max 2 items.
- nextActions: max 2 items.

Required JSON shape:
{{
  "requirementSummary": "...",
  "missingInformation": [],
  "recommendedProfile": "...",
  "reasoning": [
    "Short decision or inference grounded in the requirement and retrieved documents."
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
    {{"tool": "scaffold_runner", "mode": "dry-run | execute", "reason": "..."}},
    {{"tool": "artifact_patcher", "mode": "dry-run | execute", "reason": "..."}},
    {{"tool": "validation", "mode": "dry-run | execute", "reason": "Run only make generate, make manifests, and make test."}}
  ],
  "risks": [],
  "nextActions": []
}}

Context:
Requirement text:
{requirement_text}

Reference Knowledge and Few-shot Examples:
{retrieved_docs}

Requirement intent analysis:
{intent_analysis}

Selected profile hint:
{profile_summary}

Other profile candidates:
{profile_candidates}

Safety mode:
{safety_mode}

Tool planning rules:
- For dry-run mode, include spec_generator, command_planner, and scaffold_runner in dry-run mode.
- For execute mode, include spec_generator, command_planner, scaffold_runner, artifact_patcher, and validation.
- validation means the fixed allowlisted sequence: make generate, make manifests, make test.
- Do not invent shell commands or tools outside the listed Tool names.
- Documents with category "example" are few-shot examples. Use their structure as guidance, but do not copy fields or domain values unless the current requirement asks for them.
- Documents with category "guide" or "troubleshooting" are reference knowledge. Ground planning decisions in these documents when relevant.
- The selected profile is a hint for defaults/e2e rules only. The actual Operator kind, fields, managed resources, and workflow must come from the requirement text.
- If important information is missing, list it in missingInformation and keep mutating steps dry-run unless the user explicitly provided enough detail and --execute is allowed.
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

Strict output rules:
- Use exactly the keys in the required JSON shape.
- Do not replace "decision" with "type".
- Do not replace "rootCause" with "cause".
- Do not replace "recommendedFixes" with "resolution".
- If the run passed but warnings exist, set decision to "succeeded-with-warning".
- If jobSpecValidation.passed is true and the warning is GPU shortage, explain that the Controller and Job spec are valid and the Pod is Pending because the local cluster has no GPU.
- Return JSON only.

Context:
summary.json:
{summary_json}

analysis.md:
{analysis_md}

Retrieved troubleshooting docs:
{retrieved_docs}
"""


TOOL_RESULT_EVALUATION_PROMPT = """\
Evaluate executed Tool results and return a final execution summary JSON object.

Required JSON shape:
{{
  "executionDecision": "succeeded | failed | partially-succeeded",
  "completedSteps": [],
  "failedSteps": [],
  "generatedArtifacts": [],
  "validationResults": {{
    "makeGenerate": "succeeded | failed | skipped",
    "makeManifests": "succeeded | failed | skipped",
    "makeTest": "succeeded | failed | skipped"
  }},
  "evidence": [],
  "warnings": [],
  "recommendedNextActions": [],
  "beginnerSummary": "..."
}}

Strict output rules:
- Use exactly the keys in the required JSON shape.
- Decide "succeeded" only when all executed Tools succeeded and there are no rejected Tool calls or critical errors.
- Decide "partially-succeeded" when some Tools succeeded but some Tool calls were rejected or not executed.
- Decide "failed" when any executed Tool failed or a critical error exists.
- Use concrete evidence from exitCode, status, generated files, stdout/stderr summaries, and rejected Tool calls.
- Explain the result for a beginner in one short paragraph.
- Return JSON only.

Context:
Initial requirement summary:
{requirement_summary}

Initial planned steps:
{planned_steps}

Initial tool calls:
{tool_calls}

Validated Tool calls:
{validated_tool_calls}

Rejected Tool calls:
{rejected_tool_calls}

Executed Tool results:
{tool_results}

Generated files:
{generated_files}

Warnings:
{warnings}

Errors:
{errors}
"""


RECOVERY_PLANNER_PROMPT = """\
Create a recovery plan JSON object for a failed Kubebuilder Operator automation run.

Required JSON shape:
{{
  "decision": "recovery-required | manual-review-required | unrecoverable",
  "classification": "...",
  "rootCause": "...",
  "evidence": [],
  "proposedFixes": [],
  "recoveryToolCalls": [
    {{
      "tool": "...",
      "mode": "dry-run | execute",
      "reason": "...",
      "requiresApproval": true
    }}
  ],
  "rerunFromStep": "...",
  "risks": [],
  "beginnerSummary": "..."
}}

Strict output rules:
- Do not propose automatic execution.
- Every recoveryToolCalls item must include "requiresApproval": true.
- Prefer the smallest safe recovery step.
- If the failure is caused by invalid Go types or generated code, explain the exact file or field when evidence is available.
- If evidence is insufficient, set decision to "manual-review-required".
- Return JSON only.

Context:
Initial requirement summary:
{requirement_summary}

Initial Tool plan:
{tool_plan}

Successful Tool results:
{successful_tool_results}

Failed Tool result:
{failed_tool_result}

Failure context:
{failure_context}

Retrieved troubleshooting docs:
{retrieved_docs}

Agent mode:
{agent_mode}
"""
