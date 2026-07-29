from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MailIn(StrictModel):
    provider_message_id: str = Field(min_length=1, max_length=300)
    provider_thread_id: str | None = None
    rfc_message_id: str | None = None
    sender: str = Field(min_length=1, max_length=500)
    recipients: list[str] = []
    subject: str = Field(min_length=1, max_length=500)
    body_text: str = Field(min_length=1)
    body_html: str | None = None
    received_at: datetime | None = None


class DispatchConfirmIn(StrictModel):
    team_key: str | None = None
    workflow_key: str | None = None


class VersionAction(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(default="执行流程动作", min_length=1, max_length=1000)


class PlanIn(VersionAction):
    workflow_key: str | None = None


class AgentOutputIn(StrictModel):
    output: dict[str, Any]
    evidence: list[dict[str, Any]] = []


class WorkItemReviewIn(StrictModel):
    decision: Literal["accept", "revise"]
    reason: str = Field(min_length=1)


class ApprovalDecisionIn(StrictModel):
    decision: Literal["approve", "reject", "changes_requested"]
    reason: str = Field(min_length=1)


class OperationPrepareIn(StrictModel):
    approval_id: str
    operation_key: str = Field(min_length=4, max_length=200)


class OperationExecuteIn(StrictModel):
    simulate_unknown: bool = False


class OperationVerifyIn(StrictModel):
    outcome: Literal["succeeded", "failed"]

class WorkItemUpdateIn(StrictModel):
    expected_version: int = Field(ge=1)
    title: str | None = None
    objective: str | None = None
    assigned_agent_profile_id: str | None = None
    skill_release_id: str | None = None
    acceptance_criteria: list[str] | None = None
    evidence_requirements: list[str] | None = None


class DependencyIn(StrictModel):
    work_item_id: str
    depends_on_id: str


class ToolInvokeIn(StrictModel):
    action: str
    parameters: dict[str, Any] = {}


class CollaborationIn(StrictModel):
    receiving_team_key: str
    objective: str = Field(min_length=1)
    expected_artifact: str = Field(min_length=1)
    input_scope: dict[str, Any] = {}


class CollaborationResponseIn(StrictModel):
    status: Literal["ACCEPTED", "IN_PROGRESS", "COMPLETED", "REJECTED"]
    response: dict[str, Any] = {}


class MemoryProposalIn(StrictModel):
    mission_id: str
    memory_type: str
    subject_key: str
    content: dict[str, Any]
    source_artifact_id: str | None = None


class MemoryDecisionIn(StrictModel):
    decision: Literal["approve", "reject"]

class ControlIn(StrictModel):
    scope_type: Literal["company", "team", "mission"]
    scope_id: str
    paused: bool
    reason: str = Field(min_length=1)


class DeleteOperationalDataIn(StrictModel):
    confirmation: Literal["DELETE OPERATIONAL DATA"]


class AgentExecuteIn(StrictModel):
    force_provider: Literal["configured"] = "configured"


class DispatchFeedbackIn(StrictModel):
    confirmed_team_key: str
    corrected_risk_level: Literal["low", "medium", "high", "critical"] | None = None
    comment: str = Field(default="", max_length=2000)


class TenantPolicyIn(StrictModel):
    config: dict[str, Any]
    expected_version: int | None = Field(default=None, ge=1)


class SkillTestIn(StrictModel):
    test_input: dict[str, Any] = {}


class OperationActionUpdateIn(StrictModel):
    expected_content_hash: str
    exact_action: dict[str, Any]
