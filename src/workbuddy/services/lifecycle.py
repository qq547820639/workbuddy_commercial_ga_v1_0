from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    AgentRun,
    ApprovalDecision,
    ApprovalRequest,
    Artifact,
    AuditEvent,
    CollaborationRequest,
    DispatchDecision,
    DispatchFeedback,
    Evidence,
    ExternalOperation,
    MailMessage,
    MemoryRecord,
    Mission,
    ModelInvocation,
    OperationAttempt,
    OutboxEvent,
    ProviderWebhookEvent,
    QualityEvaluation,
    SyncRun,
    ToolCall,
    ToolGrant,
    WorkItem,
    WorkItemDependency,
)

# Operational-data models cleared on tenant reset / privacy deletion, in a
# dependency-safe deletion order. ``AuditEvent`` is intentionally excluded here:
# demo reset clears it, while privacy deletion preserves it (and records a
# separate audit entry beforehand). See ``delete_operational_data``.
OPERATIONAL_MODELS = (
    OperationAttempt,
    ToolCall,
    ToolGrant,
    ExternalOperation,
    ApprovalDecision,
    ApprovalRequest,
    QualityEvaluation,
    MemoryRecord,
    CollaborationRequest,
    Evidence,
    Artifact,
    AgentRun,
    WorkItemDependency,
    WorkItem,
    Mission,
    DispatchFeedback,
    DispatchDecision,
    ModelInvocation,
    SyncRun,
    ProviderWebhookEvent,
    MailMessage,
    OutboxEvent,
)


def delete_operational_data(session: Session, tenant_id: str, *, include_audit: bool = False) -> None:
    """Delete a tenant's operational data in dependency-safe order.

    ``include_audit=True`` also clears ``AuditEvent`` (demo reset path). The
    default preserves audit events so callers can record a deletion audit entry
    beforehand (privacy deletion path).
    """
    models = OPERATIONAL_MODELS + (AuditEvent,) if include_audit else OPERATIONAL_MODELS
    for model in models:
        session.execute(delete(model).where(model.tenant_id == tenant_id))
