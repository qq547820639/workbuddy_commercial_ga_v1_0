from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def uid() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="owner", nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),)


class TeamDefinition(Base, TimestampMixin):
    __tablename__ = "team_definitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    team_key: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "team_key", name="uq_team_key"),)


class TeamConstitutionVersion(Base, TimestampMixin):
    __tablename__ = "team_constitution_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="published", nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("team_id", "version", name="uq_team_constitution_version"),)


class WorkflowVersion(Base, TimestampMixin):
    __tablename__ = "workflow_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="published", nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("team_id", "workflow_key", "version", name="uq_workflow_version"),)


class AgentProfile(Base, TimestampMixin):
    __tablename__ = "agent_profiles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    role_key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_lead: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("team_id", "role_key", name="uq_agent_role_per_team"),)


class SkillDefinition(Base, TimestampMixin):
    __tablename__ = "skill_definitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_type: Mapped[str] = mapped_column(String(30), default="platform", nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "skill_key", name="uq_skill_key"),)


class SkillRelease(Base, TimestampMixin):
    __tablename__ = "skill_releases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    skill_id: Mapped[str] = mapped_column(ForeignKey("skill_definitions.id", ondelete="CASCADE"), nullable=False, index=True)
    semantic_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="published", nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    uploaded_by_user: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (UniqueConstraint("skill_id", "semantic_version", name="uq_skill_release"),)


class MailAccount(Base, TimestampMixin):
    __tablename__ = "mail_accounts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    address: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    watch_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sync_status: Mapped[str] = mapped_column(String(30), default="idle", nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    send_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider_subscription_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    subscription_resource: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subscription_client_state: Mapped[str | None] = mapped_column(String(500), nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "address", name="uq_mail_account"),)


class MailMessage(Base, TimestampMixin):
    __tablename__ = "mail_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str | None] = mapped_column(ForeignKey("mail_accounts.id", ondelete="SET NULL"), nullable=True)
    provider_message_id: Mapped[str] = mapped_column(String(300), nullable=False)
    provider_thread_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rfc_message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sender: Mapped[str] = mapped_column(String(500), nullable=False)
    recipients: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(30), default="NEW", nullable=False)
    direction: Mapped[str] = mapped_column(String(20), default="inbound", nullable=False)
    labels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    __table_args__ = (UniqueConstraint("tenant_id", "provider_message_id", name="uq_provider_message"),)


class DispatchDecision(Base, TimestampMixin):
    __tablename__ = "dispatch_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mail_message_id: Mapped[str] = mapped_column(ForeignKey("mail_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    suggested_team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id"), nullable=False)
    suggested_workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True)
    business_type: Mapped[str] = mapped_column(String(120), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(30), nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED", nullable=False)
    confirmed_team_id: Mapped[str | None] = mapped_column(ForeignKey("team_definitions.id"), nullable=True)
    confirmed_workflow_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True)
    model_invocation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    review_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Mission(Base, TimestampMixin):
    __tablename__ = "missions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_id: Mapped[str] = mapped_column(String(300), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="INGESTED", nullable=False, index=True)
    primary_team_id: Mapped[str | None] = mapped_column(ForeignKey("team_definitions.id"), nullable=True, index=True)
    lead_agent_profile_id: Mapped[str | None] = mapped_column(ForeignKey("agent_profiles.id"), nullable=True)
    constitution_version_id: Mapped[str | None] = mapped_column(ForeignKey("team_constitution_versions.id"), nullable=True)
    workflow_version_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_versions.id"), nullable=True)
    plan_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "source_type", "source_id", name="uq_mission_source"),)


class WorkItem(Base, TimestampMixin):
    __tablename__ = "work_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    item_key: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT", nullable=False, index=True)
    assigned_agent_profile_id: Mapped[str | None] = mapped_column(ForeignKey("agent_profiles.id"), nullable=True)
    skill_release_id: Mapped[str | None] = mapped_column(ForeignKey("skill_releases.id"), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    acceptance_criteria: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    evidence_requirements: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint("mission_id", "item_key", name="uq_work_item_key"),)


class WorkItemDependency(Base):
    __tablename__ = "work_item_dependencies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True)
    __table_args__ = (UniqueConstraint("work_item_id", "depends_on_id", name="uq_work_item_dependency"),)


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_profile_id: Mapped[str] = mapped_column(ForeignKey("agent_profiles.id"), nullable=False)
    skill_release_id: Mapped[str] = mapped_column(ForeignKey("skill_releases.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="CREATED", nullable=False, index=True)
    data_scope: Mapped[str] = mapped_column(String(100), default="current_mission", nullable=False)
    budget: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    context_cleared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    model_invocation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Artifact(Base, TimestampMixin):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    work_item_id: Mapped[str | None] = mapped_column(ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True)
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Evidence(Base, TimestampMixin):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(500), nullable=False)
    source_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_status: Mapped[str] = mapped_column(String(30), default="unverified", nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ApprovalRequest(Base, TimestampMixin):
    __tablename__ = "approval_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING", nullable=False, index=True)
    decision_question: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    alternatives: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    exact_action: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mission_version: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApprovalDecision(Base, TimestampMixin):
    __tablename__ = "approval_decisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    approval_request_id: Mapped[str] = mapped_column(ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)


class ExternalOperation(Base, TimestampMixin):
    __tablename__ = "external_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    approval_request_id: Mapped[str | None] = mapped_column(ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True)
    operation_key: Mapped[str] = mapped_column(String(200), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="PREPARED", nullable=False, index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    demo_mode: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    recipient_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    body_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attachment_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    __table_args__ = (UniqueConstraint("tenant_id", "operation_key", name="uq_operation_key"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    aggregate_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    previous_hash: Mapped[str] = mapped_column(String(64), default="0" * 64, nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "sequence", name="uq_audit_tenant_sequence"),)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dead_lettered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class IdempotencyRecord(Base, TimestampMixin):
    __tablename__ = "idempotency_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    route: Mapped[str] = mapped_column(String(300), nullable=False)
    idem_key: Mapped[str] = mapped_column(String(300), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "route", "idem_key", name="uq_idempotency"),)


Index("ix_missions_team_status", Mission.tenant_id, Mission.primary_team_id, Mission.status)
Index("ix_mail_processing", MailMessage.tenant_id, MailMessage.processing_status, MailMessage.received_at)

class ToolDefinition(Base, TimestampMixin):
    __tablename__ = "tool_definitions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_key: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(30), default="low", nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "tool_key", name="uq_tool_key"),)


class ToolGrant(Base, TimestampMixin):
    __tablename__ = "tool_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_definitions.id"), nullable=False)
    allowed_actions: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    data_scope: Mapped[str] = mapped_column(String(100), default="current_mission", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("agent_run_id", "tool_id", name="uq_run_tool_grant"),)


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_run_id: Mapped[str] = mapped_column(ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    tool_id: Mapped[str] = mapped_column(ForeignKey("tool_definitions.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(160), nullable=False)
    parameters_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CollaborationRequest(Base, TimestampMixin):
    __tablename__ = "collaboration_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    sending_team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id"), nullable=False)
    receiving_team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id"), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    input_scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    expected_artifact: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="REQUESTED", nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class MemoryRecord(Base, TimestampMixin):
    __tablename__ = "memory_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id"), nullable=False)
    agent_profile_id: Mapped[str | None] = mapped_column(ForeignKey("agent_profiles.id"), nullable=True)
    memory_type: Mapped[str] = mapped_column(String(80), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED", nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)

class SystemControl(Base, TimestampMixin):
    __tablename__ = "system_controls"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(100), nullable=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    changed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "scope_type", "scope_id", name="uq_system_control_scope"),)


class TenantPolicy(Base, TimestampMixin):
    __tablename__ = "tenant_policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    policy_key: Mapped[str] = mapped_column(String(120), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "policy_key", name="uq_tenant_policy"),)


class ModelInvocation(Base, TimestampMixin):
    __tablename__ = "model_invocations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str | None] = mapped_column(ForeignKey("missions.id", ondelete="SET NULL"), nullable=True, index=True)
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(40), default="1", nullable=False)
    usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_cny_fen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class DispatchFeedback(Base, TimestampMixin):
    __tablename__ = "dispatch_feedback"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    dispatch_decision_id: Mapped[str] = mapped_column(ForeignKey("dispatch_decisions.id", ondelete="CASCADE"), nullable=False, index=True)
    suggested_team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id"), nullable=False)
    confirmed_team_id: Mapped[str] = mapped_column(ForeignKey("team_definitions.id"), nullable=False)
    suggested_risk_level: Mapped[str] = mapped_column(String(30), nullable=False)
    corrected_risk_level: Mapped[str | None] = mapped_column(String(30), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)


class SyncRun(Base, TimestampMixin):
    __tablename__ = "sync_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("mail_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    cursor_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reused_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deleted_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebhookBinding(Base, TimestampMixin):
    """Minimal provider-to-tenant routing map intentionally outside tenant RLS.

    It contains no mail content or credentials. Webhook handlers use it to discover
    the tenant, then set PostgreSQL tenant context before accessing tenant tables.
    """
    __tablename__ = "webhook_bindings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    external_key: Mapped[str] = mapped_column(String(500), nullable=False)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("mail_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    verification_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    __table_args__ = (UniqueConstraint("provider", "external_key", name="uq_webhook_binding"),)


class ProviderWebhookEvent(Base, TimestampMixin):
    __tablename__ = "provider_webhook_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(300), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="RECEIVED", nullable=False)
    __table_args__ = (UniqueConstraint("provider", "provider_event_id", name="uq_provider_webhook_event"),)


class QualityEvaluation(Base, TimestampMixin):
    __tablename__ = "quality_evaluations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    mission_id: Mapped[str | None] = mapped_column(ForeignKey("missions.id", ondelete="CASCADE"), nullable=True, index=True)
    work_item_id: Mapped[str | None] = mapped_column(ForeignKey("work_items.id", ondelete="CASCADE"), nullable=True, index=True)
    agent_profile_id: Mapped[str | None] = mapped_column(ForeignKey("agent_profiles.id"), nullable=True)
    skill_release_id: Mapped[str | None] = mapped_column(ForeignKey("skill_releases.id"), nullable=True)
    evaluation_type: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    evaluator: Mapped[str] = mapped_column(String(100), nullable=False)


class OperationAttempt(Base, TimestampMixin):
    __tablename__ = "operation_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    operation_id: Mapped[str] = mapped_column(ForeignKey("external_operations.id", ondelete="CASCADE"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("operation_id", "attempt_number", name="uq_operation_attempt_number"),)


class PilotProgram(Base, TimestampMixin):
    __tablename__ = "pilot_programs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False, index=True)
    start_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False)
    security_owner_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    operations_owner_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    privacy_owner_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    targets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_pilot_program_name"),)


class PilotMailbox(Base, TimestampMixin):
    __tablename__ = "pilot_mailboxes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pilot_program_id: Mapped[str] = mapped_column(ForeignKey("pilot_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    mail_account_id: Mapped[str] = mapped_column(ForeignKey("mail_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(30), default="SHADOW", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    team_keys: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_recipient_domains: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    allowed_recipient_addresses: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("pilot_program_id", "mail_account_id", name="uq_pilot_mailbox"),)


class GateEvidence(Base, TimestampMixin):
    __tablename__ = "gate_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pilot_program_id: Mapped[str] = mapped_column(ForeignKey("pilot_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    gate_key: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    environment: Mapped[str] = mapped_column(String(30), default="staging", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False, index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    artifact_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    verified_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (Index("ix_gate_evidence_program_gate_type", "pilot_program_id", "gate_key", "evidence_type"),)


class GateAttestation(Base, TimestampMixin):
    __tablename__ = "gate_attestations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pilot_program_id: Mapped[str] = mapped_column(ForeignKey("pilot_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    gate_key: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("pilot_program_id", "gate_key", "role", name="uq_gate_attestation_role"),)


class OperationalDrill(Base, TimestampMixin):
    __tablename__ = "operational_drills"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pilot_program_id: Mapped[str] = mapped_column(ForeignKey("pilot_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    drill_type: Mapped[str] = mapped_column(String(100), nullable=False)
    execution_mode: Mapped[str] = mapped_column(String(30), default="SIMULATED", nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PLANNED", nullable=False, index=True)
    initiated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey("gate_evidence.id", ondelete="SET NULL"), nullable=True)


class PilotDailyMetric(Base, TimestampMixin):
    __tablename__ = "pilot_daily_metrics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pilot_program_id: Mapped[str] = mapped_column(ForeignKey("pilot_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_date: Mapped[str] = mapped_column(String(10), nullable=False)
    mailbox_id: Mapped[str | None] = mapped_column(ForeignKey("pilot_mailboxes.id", ondelete="CASCADE"), nullable=True, index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="operator", nullable=False)
    __table_args__ = (UniqueConstraint("pilot_program_id", "metric_date", "mailbox_id", name="uq_pilot_daily_metric"),)


class PilotIncident(Base, TimestampMixin):
    __tablename__ = "pilot_incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pilot_program_id: Mapped[str] = mapped_column(ForeignKey("pilot_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False)


class ProductPlan(Base, TimestampMixin):
    __tablename__ = "product_plans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_key: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    monthly_price_cny_fen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    annual_price_cny_fen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entitlements: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    overage_rates: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "plan_key", "version", name="uq_product_plan_version"),)


class TenantSubscription(Base, TimestampMixin):
    __tablename__ = "tenant_subscriptions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(ForeignKey("product_plans.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="TRIALING", nullable=False, index=True)
    billing_cycle: Mapped[str] = mapped_column(String(20), default="monthly", nullable=False)
    current_period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="manual", nullable=False)
    provider_customer_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    provider_subscription_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class UsageRecord(Base, TimestampMixin):
    __tablename__ = "usage_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    cost_cny_fen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_type: Mapped[str] = mapped_column(String(80), nullable=False)
    source_id: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_usage_idempotency"),)


class BillingEvent(Base, TimestampMixin):
    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[str | None] = mapped_column(ForeignKey("tenant_subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), default="RECORDED", nullable=False, index=True)
    amount_cny_fen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="internal_ledger", nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_billing_event_idempotency"),)


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    subscription_id: Mapped[str] = mapped_column(ForeignKey("tenant_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), default="CNY", nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subtotal_cny_fen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tax_cny_fen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_cny_fen: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lines: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    provider: Mapped[str] = mapped_column(String(40), default="internal_ledger", nullable=False)
    provider_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    tax_type: Mapped[str] = mapped_column(String(30), default="VAT", nullable=False)
    tax_region: Mapped[str] = mapped_column(String(30), default="CN", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "invoice_number", name="uq_invoice_number"),)


class CustomerOnboarding(Base, TimestampMixin):
    __tablename__ = "customer_onboardings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pilot_program_id: Mapped[str | None] = mapped_column(ForeignKey("pilot_programs.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(40), default="DISCOVERY", nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False)
    target_go_live_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checklist: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    risks: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    design_partner_profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_customer_onboarding_name"),)


class SupportTicket(Base, TimestampMixin):
    __tablename__ = "support_tickets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_number: Mapped[str] = mapped_column(String(100), nullable=False)
    requester_id: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", nullable=False, index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(200), nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "ticket_number", name="uq_support_ticket_number"),)


class ServiceStatusIncident(Base, TimestampMixin):
    __tablename__ = "service_status_incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    incident_key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    impact: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="INVESTIGATING", nullable=False, index=True)
    public_message: Mapped[str] = mapped_column(Text, nullable=False)
    components: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "incident_key", name="uq_service_incident_key"),)


class ComplianceDocument(Base, TimestampMixin):
    __tablename__ = "compliance_documents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    document_key: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False, index=True)
    artifact_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    jurisdiction: Mapped[str] = mapped_column(String(30), default="CN", nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "document_key", "version", name="uq_compliance_document_version"),)


class TenantAgreement(Base, TimestampMixin):
    __tablename__ = "tenant_agreements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("compliance_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    accepted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    document_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "document_id", name="uq_tenant_document_agreement"),)


class CustomerValueMetric(Base, TimestampMixin):
    __tablename__ = "customer_value_metrics"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    metric_date: Mapped[str] = mapped_column(String(10), nullable=False)
    metric_key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "metric_date", "metric_key", name="uq_customer_value_metric"),)


class GAReleaseProgram(Base, TimestampMixin):
    __tablename__ = "ga_release_programs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    pilot_program_id: Mapped[str | None] = mapped_column(ForeignKey("pilot_programs.id", ondelete="SET NULL"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False, index=True)
    targets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_ga_program_name"),)


class GAEvidence(Base, TimestampMixin):
    __tablename__ = "ga_evidence"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    ga_program_id: Mapped[str] = mapped_column(ForeignKey("ga_release_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    gate_key: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    artifact_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(200), nullable=False)
    verified_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (Index("ix_ga_evidence_program_gate_type", "ga_program_id", "gate_key", "evidence_type"),)


class GAAttestation(Base, TimestampMixin):
    __tablename__ = "ga_attestations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    ga_program_id: Mapped[str] = mapped_column(ForeignKey("ga_release_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    gate_key: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    cryptographic_signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    signing_key_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    __table_args__ = (UniqueConstraint("ga_program_id", "gate_key", "role", name="uq_ga_attestation_role"),)


# ---------------------------------------------------------------------------
# Gap-closure models (migrations 0011–0019)
# ---------------------------------------------------------------------------

class PricingApproval(Base, TimestampMixin):
    """Gap 1: Formal pricing approval bound to a catalog content hash."""
    __tablename__ = "pricing_approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    catalog_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approver_role: Mapped[str] = mapped_column(String(80), nullable=False)
    approver_id: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    contract_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "catalog_hash", name="uq_pricing_approval_catalog"),)


class ModelProviderAgreement(Base, TimestampMixin):
    """Gap 5: Model-provider DPA, processing region and cost rates."""
    __tablename__ = "model_provider_agreements"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    dpa_status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    dpa_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    processing_region: Mapped[str] = mapped_column(String(80), default="CN", nullable=False)
    input_cost_cny_fen_per_million: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_cost_cny_fen_per_million: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "model_name", name="uq_model_provider_agreement"),)


class PenetrationTestReport(Base, TimestampMixin):
    """Gap 7: Penetration test report — distinguishes internal automated vs external third-party."""
    __tablename__ = "penetration_test_reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    test_date: Mapped[str] = mapped_column(String(10), nullable=False)
    tester_type: Mapped[str] = mapped_column(String(40), default="INTERNAL_AUTOMATED", nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    remediation_status: Mapped[str] = mapped_column(String(40), default="PENDING", nullable=False)
    report_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    report_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class LegalReviewApproval(Base, TimestampMixin):
    """Gap 8: Legal review approval for compliance documents per jurisdiction."""
    __tablename__ = "legal_review_approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("compliance_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_role: Mapped[str] = mapped_column(String(80), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(30), default="CN", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    __table_args__ = (UniqueConstraint("document_id", "reviewer_role", "jurisdiction", name="uq_legal_review_role_jurisdiction"),)


class OnCallSchedule(Base, TimestampMixin):
    """Gap 9: On-call rotation schedule."""
    __tablename__ = "oncall_schedules"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", nullable=False)
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Shanghai", nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_oncall_schedule_name"),)


class OnCallShift(Base, TimestampMixin):
    """Gap 9: Individual on-call shift within a schedule."""
    __tablename__ = "oncall_shifts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id: Mapped[str] = mapped_column(ForeignKey("oncall_schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    responder_id: Mapped[str] = mapped_column(String(200), nullable=False)
    responder_contact: Mapped[str] = mapped_column(String(500), nullable=False)
    role: Mapped[str] = mapped_column(String(30), default="primary", nullable=False)
    shift_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    shift_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (Index("ix_oncall_shift_schedule_window", "schedule_id", "shift_start", "shift_end"),)


class EscalationPolicy(Base, TimestampMixin):
    """Gap 9: Escalation policy by severity."""
    __tablename__ = "escalation_policies"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    __table_args__ = (UniqueConstraint("tenant_id", "severity", name="uq_escalation_policy_severity"),)


class ObservationWindow(Base, TimestampMixin):
    """Gap 11: 30-day incident-free observation window for GA."""
    __tablename__ = "observation_windows"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    ga_program_id: Mapped[str] = mapped_column(ForeignKey("ga_release_programs.id", ondelete="CASCADE"), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="OBSERVING", nullable=False, index=True)
    p0_p1_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reset_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reset_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
