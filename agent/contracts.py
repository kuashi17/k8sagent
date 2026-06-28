"""Pydantic contracts for Agent planning, execution, and reporting."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentContract(BaseModel):
    """Base contract that preserves forward-compatible extension fields."""

    model_config = ConfigDict(extra="allow", strict=True)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
            exclude_unset=True,
        )


class ToolCall(AgentContract):
    tool: str = Field(min_length=1)
    mode: str | None = None
    requestedMode: str | None = None
    effectiveMode: str | None = None
    reason: str = ""
    arguments: dict[str, Any] = Field(default_factory=dict)
    mutating: bool | None = None
    executeAllowed: bool | None = None
    requiresApproval: bool | None = None
    source: str | None = None


class PlannedToolCall(ToolCall):
    mode: str


class RequirementPlan(AgentContract):
    requirementSummary: str
    missingInformation: list[Any]
    recommendedProfile: str
    plannedSteps: list[Any]
    toolCalls: list[PlannedToolCall] = Field(min_length=1)
    risks: list[Any]
    nextActions: list[Any]
    reasoning: list[Any] = Field(default_factory=list)
    ragEvidence: list[Any] = Field(default_factory=list)


class ToolResult(AgentContract):
    tool: str
    command: list[str] | str | None = None
    cwd: str | None = None
    stdout: str = ""
    stderr: str = ""
    exitCode: int
    status: str
    steps: list[dict[str, Any]] = Field(default_factory=list)
    deploymentSummary: dict[str, Any] = Field(default_factory=dict)


class ExecutionTimings(AgentContract):
    toolValidationSeconds: float = Field(ge=0)
    toolExecutionSeconds: float = Field(ge=0)


class ExecutionResult(AgentContract):
    validatedToolCalls: list[ToolCall]
    rejectedToolCalls: list[dict[str, Any]]
    deferredToolCalls: list[dict[str, Any]]
    toolResults: list[ToolResult]
    timings: ExecutionTimings


class FinalEvaluation(AgentContract):
    executionDecision: str
    completedSteps: list[Any]
    failedSteps: list[Any]
    generatedArtifacts: list[Any]
    validationResults: dict[str, Any]
    evidence: list[Any]
    warnings: list[Any]
    recommendedNextActions: list[Any]
    beginnerSummary: str


class FailureContext(AgentContract):
    failedTool: str
    failedStep: str
    exitCode: int
    command: list[str] | str | None = None
    stdoutTail: str = ""
    stderrTail: str = ""
    generatedArtifacts: list[str] = Field(default_factory=list)
    missingArtifacts: list[str] = Field(default_factory=list)
    previousSuccessfulSteps: list[str] = Field(default_factory=list)
    workspace: str
    targetProjectDir: str = ""
    agentMode: str = ""
    failedResult: dict[str, Any] = Field(default_factory=dict)


class RecoveryPlan(AgentContract):
    decision: str
    classification: str
    rootCause: str
    evidence: list[Any]
    proposedFixes: list[Any]
    recoveryToolCalls: list[PlannedToolCall]
    validatedRecoveryToolCalls: list[ToolCall] = Field(default_factory=list)
    rejectedRecoveryToolCalls: list[dict[str, Any]] = Field(
        default_factory=list
    )
    rerunFromStep: str
    risks: list[Any]
    beginnerSummary: str
    status: str = ""


class AgentSummary(AgentContract):
    mode: Literal["requirement-planning"]
    requirement: str
    profile: str
    planner: str
    llmPlannerUsed: bool
    localLLM: dict[str, Any]
    llmError: str
    agentMode: str
    runLevel: str
    executeAllowed: bool
    createdAt: str
    requirementSummary: dict[str, Any]
    missingInformation: list[Any]
    llmPlan: dict[str, Any]
    validatedToolCalls: list[ToolCall]
    rejectedToolCalls: list[dict[str, Any]]
    deferredToolCalls: list[dict[str, Any]]
    generatedFiles: dict[str, Any]
    targetProjectDir: str
    toolResults: list[ToolResult]
    finalLLM: dict[str, Any]
    failureContext: dict[str, Any]
    recovery: dict[str, Any]
    warnings: list[Any]
    errors: list[Any]
    nextRecommendedActions: list[Any]


class AgentTechnicalDetails(AgentContract):
    kind: str = ""
    managedResources: list[str] = Field(default_factory=list)
    completedSteps: list[str] = Field(default_factory=list)
    failedSteps: list[str] = Field(default_factory=list)
    generatedArtifacts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    nextActions: list[str] = Field(default_factory=list)
    capabilitySupport: list[dict[str, Any]] = Field(default_factory=list)
    beginnerExplanation: list[str] = Field(default_factory=list)
    codeExplanation: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(AgentContract):
    type: Literal["capability", "execution", "recovery"]
    required: bool = True
    reason: str
    proposalPath: str = ""


class AgentResult(AgentContract):
    """Single presentation contract shared by Agent artifacts and Web UI."""

    status: str
    succeeded: bool
    beginnerSummary: str
    technicalDetails: AgentTechnicalDetails
    approvalRequests: list[ApprovalRequest] = Field(default_factory=list)
    validationResults: dict[str, Any] = Field(default_factory=dict)
    recoveryState: dict[str, Any] = Field(default_factory=dict)
    canExecute: bool = False


LLM_OUTPUT_CONTRACTS: dict[str, type[AgentContract]] = {
    "requirement-planning": RequirementPlan,
    "tool-result-evaluation": FinalEvaluation,
    "recovery-planning": RecoveryPlan,
}


def validate_contract(
    contract: type[AgentContract],
    value: dict[str, Any],
) -> dict[str, Any]:
    return contract.model_validate(value).to_dict()
