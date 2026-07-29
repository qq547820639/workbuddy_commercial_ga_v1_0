from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.api.deps import db_session, require_tenant, tenant_id
from workbuddy.db.models import (
    AgentRun, AuditEvent, ComplianceDocument, ExternalOperation, GAAttestation, GateEvidence,
    Invoice, MailAccount, Mission, OutboxEvent, PilotIncident, PilotProgram, SupportTicket,
    SyncRun, TenantSubscription,
)
from workbuddy.services.audit import verify_audit_chain
from workbuddy.services.pilot import go_no_go_report
from workbuddy.settings import settings

router = APIRouter(tags=["operations"])


def _preflight(session: Session, tenant_id: str) -> dict:
    dialect = session.bind.dialect.name if session.bind else "unknown"
    production = settings.environment.lower() in {"production", "prod"}
    checks = {
        "database_reachable": True,
        "postgresql_in_production": (not production) or dialect == "postgresql",
        "https_public_url_in_production": (not production) or settings.public_base_url.startswith("https://"),
        "production_authentication": (not production) or settings.auth_mode in {"jwt", "oidc"},
        "strong_app_secret": len(settings.app_secret) >= 32 and not settings.app_secret.startswith("local-development"),
        "token_encryption_key_configured": bool(settings.token_encryption_key),
        "backup_target_configured": bool(settings.backup_bucket),
        "alert_target_configured": bool(settings.alert_webhook_url),
        "model_provider_configured": settings.model_provider == "deterministic" or bool(settings.model_api_key),
        "live_send_default_safe": (not settings.enable_live_email_send) or settings.live_send_ready,
        "pilot_gate_enforced_for_live_send": (not production) or settings.require_pilot_for_live_send,
        "production_object_store": (not production) or settings.object_store_provider.lower() == "s3",
        "object_store_encryption_configured": (not production) or bool(settings.object_store_kms_key_arn),
        "cloud_infra_references_configured": (not production) or bool(settings.gcp_project_id and settings.entra_tenant_id),
        "billing_tax_region_configured": bool(settings.tax_default_region),
    }
    valid, broken = verify_audit_chain(session, tenant_id)
    checks["audit_chain_valid"] = valid
    return {
        "ready": all(checks.values()), "environment": settings.environment, "database_dialect": dialect,
        "checks": checks, "audit_broken_at": broken,
        "note": "External provider registration, legal/privacy approval and live operational evidence are evaluated in the pilot gate report, not inferred from configuration.",
    }


@router.get("/v1/ops/preflight")
def preflight(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid); session.execute(select(1)); return _preflight(session, tid)


@router.get("/v1/ops/status")
def ops_status(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    program = session.scalar(select(PilotProgram).where(PilotProgram.tenant_id == tid).order_by(PilotProgram.created_at.desc()).limit(1))
    return {
        "preflight": _preflight(session, tid),
        "pilot": go_no_go_report(session, tid, program.id) if program else None,
        "counts": {
            "missions_active": session.scalar(select(func.count()).select_from(Mission).where(Mission.tenant_id == tid, Mission.status.notin_(["COMPLETED", "FAILED", "CANCELLED"]))) or 0,
            "agent_runs_active": session.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == tid, AgentRun.status.in_(["RUNNING", "TOOL_WAIT"]))) or 0,
            "outbox_pending": session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.tenant_id == tid, OutboxEvent.published_at.is_(None), OutboxEvent.dead_lettered.is_(False))) or 0,
            "external_unknown": session.scalar(select(func.count()).select_from(ExternalOperation).where(ExternalOperation.tenant_id == tid, ExternalOperation.status == "UNKNOWN")) or 0,
            "sync_failed": session.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.tenant_id == tid, SyncRun.status == "FAILED")) or 0,
            "open_p0_p1": session.scalar(select(func.count()).select_from(PilotIncident).where(PilotIncident.tenant_id == tid, PilotIncident.severity.in_(["P0", "P1"]), PilotIncident.status != "RESOLVED")) or 0,
        },
    }


@router.get("/metrics/prometheus")
def prometheus_metrics(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    rows = {
        "workbuddy_missions_active": session.scalar(select(func.count()).select_from(Mission).where(Mission.tenant_id == tid, Mission.status.notin_(["COMPLETED", "FAILED", "CANCELLED"]))) or 0,
        "workbuddy_agent_runs_active": session.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.tenant_id == tid, AgentRun.status.in_(["RUNNING", "TOOL_WAIT"]))) or 0,
        "workbuddy_outbox_pending": session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.tenant_id == tid, OutboxEvent.published_at.is_(None), OutboxEvent.dead_lettered.is_(False))) or 0,
        "workbuddy_external_operations_unknown": session.scalar(select(func.count()).select_from(ExternalOperation).where(ExternalOperation.tenant_id == tid, ExternalOperation.status == "UNKNOWN")) or 0,
        "workbuddy_sync_runs_failed": session.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.tenant_id == tid, SyncRun.status == "FAILED")) or 0,
        "workbuddy_mail_accounts_active": session.scalar(select(func.count()).select_from(MailAccount).where(MailAccount.tenant_id == tid, MailAccount.status == "active")) or 0,
        "workbuddy_gate_evidence_verified": session.scalar(select(func.count()).select_from(GateEvidence).where(GateEvidence.tenant_id == tid, GateEvidence.status == "VERIFIED")) or 0,
        "workbuddy_audit_events_total": session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tid)) or 0,
        "workbuddy_pilot_open_p0_p1": session.scalar(select(func.count()).select_from(PilotIncident).where(PilotIncident.tenant_id == tid, PilotIncident.severity.in_(["P0", "P1"]), PilotIncident.status != "RESOLVED")) or 0,
        "workbuddy_commercial_subscriptions_active": session.scalar(select(func.count()).select_from(TenantSubscription).where(TenantSubscription.tenant_id == tid, TenantSubscription.status.in_(["TRIALING", "ACTIVE"]))) or 0,
        "workbuddy_commercial_invoices_draft": session.scalar(select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tid, Invoice.status == "DRAFT")) or 0,
        "workbuddy_commercial_invoices_unpaid": session.scalar(select(func.count()).select_from(Invoice).where(Invoice.tenant_id == tid, Invoice.status.in_(["DRAFT", "OPEN"]))) or 0,
        "workbuddy_support_tickets_open": session.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.tenant_id == tid, SupportTicket.status.not_in(["RESOLVED", "CLOSED"]))) or 0,
        "workbuddy_support_tickets_p0_p1_open": session.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.tenant_id == tid, SupportTicket.severity.in_(["P0", "P1"]), SupportTicket.status.not_in(["RESOLVED", "CLOSED"]))) or 0,
        "workbuddy_ga_attestations_approved": session.scalar(select(func.count()).select_from(GAAttestation).where(GAAttestation.tenant_id == tid, GAAttestation.decision == "APPROVE")) or 0,
        "workbuddy_compliance_documents_published": session.scalar(select(func.count()).select_from(ComplianceDocument).where(ComplianceDocument.tenant_id == tid, ComplianceDocument.status == "PUBLISHED")) or 0,
    }
    text = "\n".join([f"# TYPE {key} gauge\n{key} {value}" for key, value in rows.items()]) + "\n"
    return Response(text, media_type="text/plain; version=0.0.4")
