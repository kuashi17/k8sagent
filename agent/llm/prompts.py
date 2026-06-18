"""Prompts for LLM based Agent planning."""

from __future__ import annotations


SYSTEM_PROMPT = """\
You plan safe Kubebuilder Operator workflows.
Use the requirement as the source of truth; profiles and retrieved documents are hints.
Never invent tools or shell commands. Keep mutating tools in dry-run unless execute is allowed.
Return one compact JSON object only, with no Markdown.
"""


REQUIREMENT_PLANNER_PROMPT = """\
Plan this requirement. Use every required key and keep all strings short.
Required shape and key order:
{{
  "requirementSummary": "...",
  "toolCalls": [
    {tool_call_examples}
  ],
  "missingInformation": [],
  "recommendedProfile": "...",
  "plannedSteps": [],
  "risks": [],
  "nextActions": []
}}

Limits: missingInformation 4; plannedSteps 4; risks 2; nextActions 2;
each Tool reason is at most 10 words.

Requirement:
{requirement_text}

References:
{retrieved_docs}

Intent:
{intent_analysis}

Profile hint:
{profile_summary}

Profile candidates:
{profile_candidates}

Workflow:
{workflow_options}

Safety:
{safety_mode}

Rules:
- dry-run: spec_generator, command_planner, scaffold_runner.
- execute: also artifact_patcher and validation.
- validation means make generate, make manifests, make test.
{kind_deployment_rule}
- Never copy example fields absent from the requirement.
- Missing important data keeps mutating steps dry-run.
"""


REQUIREMENT_PLAN_REPAIR_PROMPT = """\
Repair the candidate into one compact JSON object. Do not explain.
Required keys and types:
- requirementSummary: string
- toolCalls: array of objects with non-empty tool, mode, reason
- missingInformation: array
- recommendedProfile: string
- plannedSteps: array
- risks: array
- nextActions: array

Allowed tools: spec_generator, command_planner, scaffold_runner, artifact_patcher, validation{optional_kind_tool_name}
Safety mode: {safety_mode}
Workflow: {workflow_options}
Validation errors: {validation_errors}
Candidate:
{candidate}
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
