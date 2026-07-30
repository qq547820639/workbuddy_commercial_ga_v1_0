"""Operations domain: support tickets, status incidents, compliance/legal documents, model agreements, pentests and observation windows."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    ComplianceDocument, LegalReviewApproval, ModelProviderAgreement, ObservationWindow,
    PenetrationTestReport, PilotIncident, ServiceStatusIncident, SupportTicket, TenantAgreement,
)
from workbuddy.services.audit import append_audit
from workbuddy.services.common import content_hash, naive_utc, utcnow

from ._common import CommercialError, SLA_HOURS


def create_support_ticket(session: Session, tenant_id: str, actor_id: str, *, severity: str, category: str, title: str, description: str) -> SupportTicket:
    if severity not in SLA_HOURS: raise CommercialError("severity must be P0, P1, P2 or P3")
    now = utcnow(); count = session.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.tenant_id == tenant_id)) or 0
    ticket = SupportTicket(tenant_id=tenant_id, ticket_number=f"WB-SUP-{now.strftime('%Y%m%d')}-{count+1:04d}", requester_id=actor_id, severity=severity, category=category, title=title, description=description, sla_due_at=now + timedelta(hours=SLA_HOURS[severity]))
    session.add(ticket); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.support_ticket_created", aggregate_type="SupportTicket", aggregate_id=ticket.id, payload={"ticket_number": ticket.ticket_number, "severity": severity})
    return ticket


def update_support_ticket(session: Session, tenant_id: str, ticket_id: str, actor_id: str, *, status: str, assigned_to: str | None = None, resolution: str | None = None) -> SupportTicket:
    ticket = session.scalar(select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.tenant_id == tenant_id))
    if not ticket: raise CommercialError("support ticket not found")
    allowed = {"OPEN": {"IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED"}, "IN_PROGRESS": {"WAITING_CUSTOMER", "RESOLVED"}, "WAITING_CUSTOMER": {"IN_PROGRESS", "RESOLVED"}, "RESOLVED": {"CLOSED"}, "CLOSED": set()}
    if status not in allowed.get(ticket.status, set()): raise CommercialError(f"invalid ticket transition {ticket.status} -> {status}")
    if status == "RESOLVED" and not resolution: raise CommercialError("resolution is required")
    before = ticket.status; ticket.status = status
    if assigned_to: ticket.assigned_to = assigned_to
    if status in {"IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED"} and not ticket.first_response_at: ticket.first_response_at = utcnow()
    if status == "RESOLVED": ticket.resolved_at = utcnow(); ticket.resolution = resolution
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.support_ticket_transitioned", aggregate_type="SupportTicket", aggregate_id=ticket.id, payload={"from": before, "to": status, "assigned_to": assigned_to})
    return ticket


def create_status_incident(session: Session, tenant_id: str, actor_id: str, *, title: str, impact: str, public_message: str, components: list[str]) -> ServiceStatusIncident:
    now = utcnow(); count = session.scalar(select(func.count()).select_from(ServiceStatusIncident).where(ServiceStatusIncident.tenant_id == tenant_id)) or 0
    row = ServiceStatusIncident(tenant_id=tenant_id, incident_key=f"WB-INC-{now.strftime('%Y%m%d')}-{count+1:03d}", title=title, impact=impact, public_message=public_message, components=components, updates=[{"at": now.isoformat(), "status": "INVESTIGATING", "message": public_message, "actor": actor_id}])
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.status_incident_created", aggregate_type="ServiceStatusIncident", aggregate_id=row.id, payload={"impact": impact, "components": components})
    return row


def update_status_incident(session: Session, tenant_id: str, incident_id: str, actor_id: str, *, status: str, public_message: str) -> ServiceStatusIncident:
    row = session.scalar(select(ServiceStatusIncident).where(ServiceStatusIncident.id == incident_id, ServiceStatusIncident.tenant_id == tenant_id))
    if not row: raise CommercialError("service incident not found")
    allowed = {"INVESTIGATING": {"IDENTIFIED", "MONITORING", "RESOLVED"}, "IDENTIFIED": {"MONITORING", "RESOLVED"}, "MONITORING": {"RESOLVED"}, "RESOLVED": set()}
    if status not in allowed.get(row.status, set()): raise CommercialError(f"invalid incident transition {row.status} -> {status}")
    row.status = status; row.public_message = public_message
    row.updates = [*(row.updates or []), {"at": utcnow().isoformat(), "status": status, "message": public_message, "actor": actor_id}]
    if status == "RESOLVED": row.resolved_at = utcnow()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.status_incident_updated", aggregate_type="ServiceStatusIncident", aggregate_id=row.id, payload={"status": status})
    return row


def publish_compliance_document(session: Session, tenant_id: str, actor_id: str, *, document_key: str, title: str, version: str, artifact_ref: str | None, content_hash: str, jurisdiction: str = "CN") -> ComplianceDocument:
    existing = session.scalar(select(ComplianceDocument).where(ComplianceDocument.tenant_id == tenant_id, ComplianceDocument.document_key == document_key, ComplianceDocument.version == version))
    if existing: return existing
    row = ComplianceDocument(tenant_id=tenant_id, document_key=document_key, title=title, version=version, status="PUBLISHED", artifact_ref=artifact_ref, content_hash=content_hash, effective_at=utcnow(), jurisdiction=jurisdiction)
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.compliance_document_published", aggregate_type="ComplianceDocument", aggregate_id=row.id, payload={"document_key": document_key, "version": version, "content_hash": content_hash})
    return row


def accept_compliance_document(session: Session, tenant_id: str, actor_id: str, document_id: str, evidence: dict[str, Any]) -> TenantAgreement:
    document = session.scalar(select(ComplianceDocument).where(ComplianceDocument.id == document_id, ComplianceDocument.tenant_id == tenant_id, ComplianceDocument.status == "PUBLISHED"))
    if not document: raise CommercialError("published compliance document not found")
    existing = session.scalar(select(TenantAgreement).where(TenantAgreement.tenant_id == tenant_id, TenantAgreement.document_id == document_id))
    if existing: return existing
    row = TenantAgreement(tenant_id=tenant_id, document_id=document_id, accepted_by=actor_id, document_content_hash=document.content_hash, evidence=evidence)
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.compliance_document_accepted", aggregate_type="TenantAgreement", aggregate_id=row.id, payload={"document_id": document_id, "content_hash": document.content_hash})
    return row


def approve_legal_document(session: Session, tenant_id: str, actor_id: str, document_id: str, *, reviewer_role: str, decision: str, jurisdiction: str = "CN", notes: str = "") -> LegalReviewApproval:
    """Gap 8: Record a legal review approval for a compliance document."""
    if reviewer_role not in {"legal_owner", "privacy_owner"}:
        raise CommercialError("only legal_owner or privacy_owner can approve legal documents")
    if decision not in {"APPROVED", "REJECTED"}:
        raise CommercialError("decision must be APPROVED or REJECTED")
    document = session.scalar(select(ComplianceDocument).where(ComplianceDocument.id == document_id, ComplianceDocument.tenant_id == tenant_id, ComplianceDocument.status == "PUBLISHED"))
    if not document:
        raise CommercialError("published compliance document not found")
    row = session.scalar(select(LegalReviewApproval).where(LegalReviewApproval.document_id == document_id, LegalReviewApproval.reviewer_role == reviewer_role, LegalReviewApproval.jurisdiction == jurisdiction))
    if not row:
        row = LegalReviewApproval(tenant_id=tenant_id, document_id=document_id, reviewer_role=reviewer_role, reviewer_id=actor_id, decision=decision, jurisdiction=jurisdiction, notes=notes)
        session.add(row)
    else:
        row.reviewer_id = actor_id; row.decision = decision; row.notes = notes
    session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.legal_review_approved", aggregate_type="LegalReviewApproval", aggregate_id=row.id, payload={"document_id": document_id, "reviewer_role": reviewer_role, "decision": decision, "jurisdiction": jurisdiction})
    return row


def legal_approval_complete(session: Session, tenant_id: str, *, jurisdiction: str = "CN") -> bool:
    """Gap 8: Check if all 5 required documents have both legal_owner and privacy_owner approvals."""
    required_docs = {"terms", "privacy", "dpa", "subprocessors", "security_whitepaper"}
    published = session.scalars(select(ComplianceDocument).where(ComplianceDocument.tenant_id == tenant_id, ComplianceDocument.status == "PUBLISHED")).all()
    doc_ids = {d.document_key: d.id for d in published if d.document_key in required_docs}
    if not required_docs.issubset(doc_ids.keys()):
        return False
    for doc_id in doc_ids.values():
        for role in ("legal_owner", "privacy_owner"):
            approval = session.scalar(select(LegalReviewApproval).where(LegalReviewApproval.document_id == doc_id, LegalReviewApproval.reviewer_role == role, LegalReviewApproval.jurisdiction == jurisdiction, LegalReviewApproval.decision == "APPROVED"))
            if not approval:
                return False
    return True


def create_model_agreement(session: Session, tenant_id: str, actor_id: str, *, provider: str, model_name: str, dpa_status: str = "PENDING", dpa_ref: str | None = None, processing_region: str = "CN", input_cost_cny_fen_per_million: int = 0, output_cost_cny_fen_per_million: int = 0) -> ModelProviderAgreement:
    """Gap 5: Create or update a model provider agreement with DPA status and cost rates."""
    payload = {"provider": provider, "model_name": model_name, "dpa_status": dpa_status, "dpa_ref": dpa_ref, "processing_region": processing_region, "input_cost": input_cost_cny_fen_per_million, "output_cost": output_cost_cny_fen_per_million}
    row = session.scalar(select(ModelProviderAgreement).where(ModelProviderAgreement.tenant_id == tenant_id, ModelProviderAgreement.provider == provider, ModelProviderAgreement.model_name == model_name))
    if not row:
        row = ModelProviderAgreement(tenant_id=tenant_id, provider=provider, model_name=model_name, dpa_status=dpa_status, dpa_ref=dpa_ref, processing_region=processing_region, input_cost_cny_fen_per_million=input_cost_cny_fen_per_million, output_cost_cny_fen_per_million=output_cost_cny_fen_per_million, content_hash=content_hash(payload))
        session.add(row)
    else:
        row.dpa_status = dpa_status; row.dpa_ref = dpa_ref; row.processing_region = processing_region
        row.input_cost_cny_fen_per_million = input_cost_cny_fen_per_million; row.output_cost_cny_fen_per_million = output_cost_cny_fen_per_million
        row.content_hash = content_hash(payload)
        if dpa_status == "SIGNED":
            row.approved_by = actor_id; row.approved_at = utcnow(); row.effective_at = utcnow()
    session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.model_agreement_created", aggregate_type="ModelProviderAgreement", aggregate_id=row.id, payload={"provider": provider, "model_name": model_name, "dpa_status": dpa_status})
    return row


def create_pentest_report(session: Session, tenant_id: str, actor_id: str, *, test_date: str, tester_type: str = "INTERNAL_AUTOMATED", scope: str, findings: list[dict[str, Any]] | None = None, remediation_status: str = "PENDING", report_ref: str | None = None, report_hash: str | None = None) -> PenetrationTestReport:
    """Gap 7: Record a penetration test report."""
    if tester_type not in {"INTERNAL_AUTOMATED", "EXTERNAL_THIRD_PARTY"}:
        raise CommercialError("tester_type must be INTERNAL_AUTOMATED or EXTERNAL_THIRD_PARTY")
    actual_hash = report_hash or content_hash({"test_date": test_date, "tester_type": tester_type, "scope": scope, "findings": findings or []})
    row = PenetrationTestReport(tenant_id=tenant_id, test_date=test_date, tester_type=tester_type, scope=scope, findings=findings or [], remediation_status=remediation_status, report_ref=report_ref, report_hash=actual_hash, approved_by=actor_id if remediation_status == "ALL_REMEDIATED" else None)
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.pentest_report_created", aggregate_type="PenetrationTestReport", aggregate_id=row.id, payload={"test_date": test_date, "tester_type": tester_type, "remediation_status": remediation_status})
    return row


def start_observation_window(session: Session, tenant_id: str, actor_id: str, program_id: str, *, days: int = 30) -> ObservationWindow:
    """Gap 11: Start a 30-day observation window for a GA program."""
    existing = session.scalar(select(ObservationWindow).where(ObservationWindow.tenant_id == tenant_id, ObservationWindow.ga_program_id == program_id, ObservationWindow.status == "OBSERVING"))
    if existing:
        return existing
    now = utcnow()
    payload = {"program_id": program_id, "window_start": now.isoformat(), "days": days}
    row = ObservationWindow(tenant_id=tenant_id, ga_program_id=program_id, window_start=now, window_end=now + timedelta(days=days), status="OBSERVING", content_hash=content_hash(payload))
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.observation_window_started", aggregate_type="ObservationWindow", aggregate_id=row.id, payload={"program_id": program_id, "days": days})
    return row


def check_observation_window(session: Session, tenant_id: str, program_id: str) -> ObservationWindow | None:
    """Gap 11: Check observation window for P0/P1 incidents. Reset if found, complete if 30 days passed."""
    window = session.scalar(select(ObservationWindow).where(ObservationWindow.tenant_id == tenant_id, ObservationWindow.ga_program_id == program_id, ObservationWindow.status == "OBSERVING"))
    if not window:
        return None
    now = utcnow()
    # Count P0/P1 incidents in the window
    support_p0p1 = session.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.tenant_id == tenant_id, SupportTicket.severity.in_(["P0", "P1"]), SupportTicket.created_at >= window.window_start, SupportTicket.created_at <= now)) or 0
    status_p0p1 = session.scalar(select(func.count()).select_from(ServiceStatusIncident).where(ServiceStatusIncident.tenant_id == tenant_id, ServiceStatusIncident.impact.in_(["critical", "major"]), ServiceStatusIncident.started_at >= window.window_start, ServiceStatusIncident.started_at <= now)) or 0
    pilot_p0p1 = session.scalar(select(func.count()).select_from(PilotIncident).where(PilotIncident.tenant_id == tenant_id, PilotIncident.severity.in_(["P0", "P1"]), PilotIncident.detected_at >= window.window_start, PilotIncident.detected_at <= now)) or 0
    total_p0p1 = int(support_p0p1 + status_p0p1 + pilot_p0p1)
    if total_p0p1 > window.p0_p1_count:
        # New P0/P1 detected — reset the window
        window.p0_p1_count = total_p0p1
        window.reset_count += 1
        window.reset_reason = f"P0/P1 incident detected during observation (total: {total_p0p1})"
        window.window_start = now
        window.window_end = now + timedelta(days=30)
        append_audit(session, tenant_id=tenant_id, actor_type="system", actor_id="observation-checker", action="commercial.observation_window_reset", aggregate_type="ObservationWindow", aggregate_id=window.id, payload={"reset_count": window.reset_count, "p0_p1_count": total_p0p1})
    elif naive_utc(now) >= naive_utc(window.window_end) and window.p0_p1_count == 0:
        # Window completed with no P0/P1
        window.status = "COMPLETED"
        window.completed_at = now
        append_audit(session, tenant_id=tenant_id, actor_type="system", actor_id="observation-checker", action="commercial.observation_window_completed", aggregate_type="ObservationWindow", aggregate_id=window.id, payload={"window_start": window.window_start.isoformat(), "window_end": window.window_end.isoformat()})
    session.flush()
    return window
