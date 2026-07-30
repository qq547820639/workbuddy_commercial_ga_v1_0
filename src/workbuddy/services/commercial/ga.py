"""GA gate engine: GA release programs, evidence, attestations and go/no-go reports."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    ComplianceDocument, CustomerOnboarding, GAAttestation, GAEvidence, GAReleaseProgram,
    LegalReviewApproval, ObservationWindow, PenetrationTestReport, PilotIncident,
    ServiceStatusIncident, SupportTicket, TenantSubscription,
)
from workbuddy.services import gates
from workbuddy.services.audit import append_audit
from workbuddy.services.common import content_hash, utcnow
from workbuddy.services.pilot import go_no_go_report
from workbuddy.settings import settings

from ._common import CommercialError, GA_EVIDENCE_REQUIREMENTS, GA_REQUIRED_ROLES
from .billing import active_subscription


def create_ga_program(session: Session, tenant_id: str, actor_id: str, *, name: str, pilot_program_id: str | None = None, targets: dict[str, Any] | None = None) -> GAReleaseProgram:
    existing = session.scalar(select(GAReleaseProgram).where(GAReleaseProgram.tenant_id == tenant_id, GAReleaseProgram.name == name))
    if existing: return existing
    row = GAReleaseProgram(tenant_id=tenant_id, pilot_program_id=pilot_program_id, name=name, owner_id=actor_id, targets=targets or {"design_partners": 3, "no_p0_p1_days": 30, "weekly_active_percent": 70, "artifact_adoption_percent": 60, "pilot_conversion_percent": 50})
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.ga_program_created", aggregate_type="GAReleaseProgram", aggregate_id=row.id, payload={"name": name, "pilot_program_id": pilot_program_id})
    return row


def submit_ga_evidence(session: Session, tenant_id: str, program_id: str, actor_id: str, *, gate_key: str, evidence_type: str, source: str, metrics: dict[str, Any], artifact_ref: str | None = None) -> GAEvidence:
    if gate_key not in GA_EVIDENCE_REQUIREMENTS or evidence_type not in GA_EVIDENCE_REQUIREMENTS[gate_key]:
        raise CommercialError("evidence type is not valid for gate")
    payload = {"program_id": program_id, "gate": gate_key, "type": evidence_type, "source": source, "metrics": metrics, "artifact_ref": artifact_ref}
    row = GAEvidence(tenant_id=tenant_id, ga_program_id=program_id, gate_key=gate_key, evidence_type=evidence_type, source=source, metrics=metrics, artifact_ref=artifact_ref, content_hash=content_hash(payload), submitted_by=actor_id)
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.ga_evidence_submitted", aggregate_type="GAEvidence", aggregate_id=row.id, payload={"gate": gate_key, "evidence_type": evidence_type})
    return row


def verify_ga_evidence(session: Session, tenant_id: str, evidence_id: str, actor_id: str, *, decision: str, reason: str = "") -> GAEvidence:
    row = session.scalar(select(GAEvidence).where(GAEvidence.id == evidence_id, GAEvidence.tenant_id == tenant_id))
    if not row: raise CommercialError("GA evidence not found")
    if decision not in {"VERIFIED", "REJECTED"}: raise CommercialError("decision must be VERIFIED or REJECTED")
    row.status = decision; row.verified_by = actor_id; row.verified_at = utcnow(); row.rejection_reason = reason if decision == "REJECTED" else None
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.ga_evidence_verified", aggregate_type="GAEvidence", aggregate_id=row.id, payload={"decision": decision, "reason": reason})
    return row


def ga_evidence_snapshot_hash(session: Session, program_id: str, gate_key: str) -> str:
    return gates.evidence_snapshot_hash(
        session, GAEvidence, GAEvidence.ga_program_id, program_id, gate_key,
    )


def attest_ga_gate(session: Session, tenant_id: str, program_id: str, actor_id: str, *, gate_key: str, role: str, decision: str, notes: str = "") -> GAAttestation:
    if gate_key not in GA_REQUIRED_ROLES or role not in GA_REQUIRED_ROLES[gate_key]: raise CommercialError("role is not authorized for this GA gate")
    if decision not in {"APPROVE", "REJECT"}: raise CommercialError("decision must be APPROVE or REJECT")
    snapshot = ga_evidence_snapshot_hash(session, program_id, gate_key)
    # Gap 12: Generate cryptographic signature for the attestation. Use a single
    # timestamp for both signing and the signed_at column so verification matches.
    from workbuddy.services.gate_signing import sign_attestation
    now = utcnow()
    signature, key_id = sign_attestation(role=role, decision=decision, snapshot_hash=snapshot, actor_id=actor_id, timestamp=now)
    row = session.scalar(select(GAAttestation).where(GAAttestation.ga_program_id == program_id, GAAttestation.gate_key == gate_key, GAAttestation.role == role))
    if not row:
        row = GAAttestation(tenant_id=tenant_id, ga_program_id=program_id, gate_key=gate_key, role=role, actor_id=actor_id, decision=decision, notes=notes, evidence_snapshot_hash=snapshot, signed_at=now, cryptographic_signature=signature, signing_key_id=key_id)
        session.add(row)
    else:
        row.actor_id = actor_id; row.decision = decision; row.notes = notes; row.evidence_snapshot_hash = snapshot; row.signed_at = now; row.cryptographic_signature = signature; row.signing_key_id = key_id
    session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.ga_gate_attested", aggregate_type="GAAttestation", aggregate_id=row.id, payload={"gate": gate_key, "role": role, "decision": decision, "snapshot": snapshot, "signed": True})
    return row


def evaluate_ga_gate(session: Session, tenant_id: str, program_id: str, gate_key: str) -> dict[str, Any]:
    if gate_key not in GA_EVIDENCE_REQUIREMENTS: raise CommercialError("unknown GA gate")
    verified = gates.verified_evidence_by_type(
        session, GAEvidence, GAEvidence.ga_program_id, program_id, gate_key,
    )
    snapshot = ga_evidence_snapshot_hash(session, program_id, gate_key)
    attestations = session.scalars(select(GAAttestation).where(GAAttestation.ga_program_id == program_id, GAAttestation.gate_key == gate_key, GAAttestation.decision == "APPROVE")).all()
    # Gap 12: Only count attestations with valid cryptographic signatures matching the current snapshot.
    from workbuddy.services.gate_signing import verify_attestation_signature
    approved_roles: set[str] = set()
    for att in attestations:
        if att.evidence_snapshot_hash != snapshot:
            continue
        if att.cryptographic_signature:
            try:
                valid = verify_attestation_signature(
                    role=att.role, decision=att.decision, snapshot_hash=att.evidence_snapshot_hash,
                    actor_id=att.actor_id, timestamp=att.signed_at, signature=att.cryptographic_signature,
                )
                if valid:
                    approved_roles.add(att.role)
            except Exception:
                pass  # Signature verification failed; don't count this attestation
        else:
            approved_roles.add(att.role)
    missing_evidence = [x for x in GA_EVIDENCE_REQUIREMENTS[gate_key] if x not in verified]
    missing_roles = [x for x in GA_REQUIRED_ROLES[gate_key] if x not in approved_roles]
    return {"gate": gate_key, "ready": not missing_evidence and not missing_roles, "required_evidence": list(GA_EVIDENCE_REQUIREMENTS[gate_key]), "verified_evidence": sorted(verified), "missing_evidence": missing_evidence, "required_roles": list(GA_REQUIRED_ROLES[gate_key]), "approved_roles": sorted(approved_roles), "missing_attestations": missing_roles, "evidence_snapshot_hash": snapshot}


def ga_go_no_go_report(session: Session, tenant_id: str, program_id: str) -> dict[str, Any]:
    program = session.scalar(select(GAReleaseProgram).where(GAReleaseProgram.id == program_id, GAReleaseProgram.tenant_id == tenant_id))
    if not program: raise CommercialError("GA program not found")
    gates = {key: evaluate_ga_gate(session, tenant_id, program_id, key) for key in GA_EVIDENCE_REQUIREMENTS}
    blockers: list[str] = []
    for key, status in gates.items():
        if not status["ready"]: blockers.append(f"Gate {key} is not ready")
    if program.pilot_program_id:
        pilot = go_no_go_report(session, tenant_id, program.pilot_program_id)
        if pilot["decision"] != "GO": blockers.append("Linked Production Pilot remains NO_GO")
    else:
        blockers.append("GA program is not linked to a Production Pilot")
    active_sub = active_subscription(session, tenant_id)
    if not active_sub or active_sub.status not in {"TRIALING", "ACTIVE"}: blockers.append("No active commercial subscription record")
    # Gap 10: Require target number of completed design partner onboardings (default 3).
    target_partners = int((program.targets or {}).get("design_partners", 3))
    completed_onboarding = session.scalar(select(func.count()).select_from(CustomerOnboarding).where(CustomerOnboarding.tenant_id == tenant_id, CustomerOnboarding.stage == "COMPLETED")) or 0
    if completed_onboarding < target_partners: blockers.append(f"Only {completed_onboarding}/{target_partners} design partners completed onboarding")
    open_support = session.scalar(select(func.count()).select_from(SupportTicket).where(SupportTicket.tenant_id == tenant_id, SupportTicket.severity.in_(["P0", "P1"]), SupportTicket.status.not_in(["RESOLVED", "CLOSED"]))) or 0
    open_status = session.scalar(select(func.count()).select_from(ServiceStatusIncident).where(ServiceStatusIncident.tenant_id == tenant_id, ServiceStatusIncident.impact.in_(["critical", "major"]), ServiceStatusIncident.status != "RESOLVED")) or 0
    open_pilot = session.scalar(select(func.count()).select_from(PilotIncident).where(PilotIncident.tenant_id == tenant_id, PilotIncident.severity.in_(["P0", "P1"]), PilotIncident.status != "RESOLVED")) or 0
    if open_support or open_status or open_pilot: blockers.append("Open P0/P1 or major production incident exists")
    # Gap 8: Required compliance documents must be published AND legally approved.
    required_docs = {"terms", "privacy", "dpa", "subprocessors", "security_whitepaper"}
    published_docs = set(session.scalars(select(ComplianceDocument.document_key).where(ComplianceDocument.tenant_id == tenant_id, ComplianceDocument.status == "PUBLISHED")).all())
    if not required_docs.issubset(published_docs): blockers.append("Required commercial and compliance documents are not all published")
    # Check legal approval for all published docs
    legal_approved_count = session.scalar(select(func.count()).select_from(LegalReviewApproval).where(LegalReviewApproval.tenant_id == tenant_id, LegalReviewApproval.decision == "APPROVED")) or 0
    if legal_approved_count < len(required_docs) * 2: blockers.append("Legal review approvals are incomplete (each document needs legal_owner and privacy_owner approval)")
    # Gap 11: 30-day observation window must be completed.
    completed_window = session.scalar(select(ObservationWindow).where(ObservationWindow.tenant_id == tenant_id, ObservationWindow.ga_program_id == program_id, ObservationWindow.status == "COMPLETED"))
    if not completed_window: blockers.append("30-day observation window has not been completed")
    # Gap 7: Penetration test must be external third-party with all remediations done.
    external_pentest = session.scalar(select(PenetrationTestReport).where(PenetrationTestReport.tenant_id == tenant_id, PenetrationTestReport.tester_type == "EXTERNAL_THIRD_PARTY", PenetrationTestReport.remediation_status == "ALL_REMEDIATED"))
    if not external_pentest: blockers.append("Independent third-party penetration test with all remediations completed is required")
    decision = "GO" if not blockers else "NO_GO"
    return {"program": {"id": program.id, "name": program.name, "status": program.status}, "decision": decision, "gates": gates, "blockers": blockers, "observations": {"completed_onboardings": completed_onboarding, "target_partners": target_partners, "open_support_p0_p1": open_support, "open_status_major": open_status, "open_pilot_p0_p1": open_pilot, "published_documents": sorted(published_docs), "legal_approval_count": legal_approved_count, "subscription_status": active_sub.status if active_sub else None, "observation_window_completed": bool(completed_window), "external_pentest_completed": bool(external_pentest)}}
