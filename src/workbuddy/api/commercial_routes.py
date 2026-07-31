from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.api.deps import actor_id, actor_roles, db_session, set_tenant_context, tenant_id
from workbuddy.db.models import (
    BillingEvent, ComplianceDocument, CustomerOnboarding, CustomerValueMetric,
    EscalationPolicy, GAAttestation, GAEvidence, GAReleaseProgram, Invoice, LegalReviewApproval,
    ModelProviderAgreement, ObservationWindow, OnCallSchedule, OnCallShift, PenetrationTestReport,
    PricingApproval, ProductPlan, ServiceStatusIncident, SupportTicket, TenantAgreement,
    TenantSubscription, UsageRecord, User, Tenant,
)
from workbuddy.services.commercial import (
    CommercialError, GA_EVIDENCE_REQUIREMENTS, GA_REQUIRED_ROLES, ONBOARDING_REQUIREMENTS,
    accept_compliance_document, active_subscription, approve_legal_document, approve_pricing,
    attest_ga_gate, build_invoice, catalog_content_hash, check_observation_window, create_ga_program,
    create_model_agreement, create_onboarding, create_pentest_report, create_status_incident,
    create_subscription, create_support_ticket, ensure_plan_catalog, evaluate_ga_gate,
    ga_go_no_go_report, pricing_is_approved, publish_compliance_document, record_usage,
    record_value_metric, start_observation_window, submit_ga_evidence, transition_invoice,
    transition_onboarding, transition_subscription, update_design_partner_profile,
    update_onboarding_checklist, update_status_incident, update_support_ticket, usage_summary,
    verify_billing_webhook, verify_ga_evidence, invite_user, update_user_role,
)
from workbuddy.services.common import model_dict
from workbuddy.services.oncall import OnCallError, create_schedule, create_shift, current_responder, oncall_coverage_complete, set_escalation_policy
from workbuddy.settings import settings

router = APIRouter(tags=["commercial-ga"])


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SubscriptionIn(Strict):
    plan_key: str
    billing_cycle: str = "monthly"
    trial_days: int = Field(default=14, ge=0, le=90)
    provider: str = "manual"


class TransitionIn(Strict):
    target: str
    provider_ref: str | None = None
    manual_evidence: bool = False


class UsageIn(Strict):
    metric_key: str
    quantity: int = Field(ge=0)
    unit: str
    source_type: str
    source_id: str
    idempotency_key: str
    cost_cny_fen: int = Field(default=0, ge=0)
    dimensions: dict[str, Any] = Field(default_factory=dict)


class InvoiceIn(Strict):
    subscription_id: str
    tax_rate_basis_points: int = Field(default=0, ge=0, le=10000)


class OnboardingIn(Strict):
    name: str
    pilot_program_id: str | None = None
    target_go_live_at: datetime | None = None


class ChecklistIn(Strict):
    updates: dict[str, Any]


class SupportIn(Strict):
    severity: str
    category: str
    title: str
    description: str


class SupportUpdateIn(Strict):
    status: str
    assigned_to: str | None = None
    resolution: str | None = None


class StatusIncidentIn(Strict):
    title: str
    impact: str
    public_message: str
    components: list[str] = Field(default_factory=list)


class StatusIncidentUpdateIn(Strict):
    status: str
    public_message: str


class ComplianceIn(Strict):
    document_key: str
    title: str
    version: str
    artifact_ref: str | None = None
    content_hash: str = Field(min_length=64, max_length=64)


class AgreementIn(Strict):
    evidence: dict[str, Any] = Field(default_factory=dict)


class ValueMetricIn(Strict):
    metric_date: str
    metric_key: str
    value: int
    unit: str
    source: str
    dimensions: dict[str, Any] = Field(default_factory=dict)




class UserInviteIn(Strict):
    email: str
    name: str
    role: str = "member"


class UserRoleIn(Strict):
    role: str


class GAProgramIn(Strict):
    name: str
    pilot_program_id: str | None = None
    targets: dict[str, Any] = Field(default_factory=dict)


class GAEvidenceIn(Strict):
    gate_key: str
    evidence_type: str
    source: str = "operator"
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_ref: str | None = None


class EvidenceDecisionIn(Strict):
    decision: str
    reason: str = ""


class GAAttestationIn(Strict):
    gate_key: str
    role: str
    decision: str
    notes: str = ""


class PricingApprovalIn(Strict):
    approver_role: str
    decision: str
    contract_ref: str | None = None
    notes: str = ""


class ModelAgreementIn(Strict):
    provider: str
    model_name: str
    dpa_status: str = "PENDING"
    dpa_ref: str | None = None
    processing_region: str = "CN"
    input_cost_cny_fen_per_million: int = Field(default=0, ge=0)
    output_cost_cny_fen_per_million: int = Field(default=0, ge=0)


class PentestReportIn(Strict):
    test_date: str
    tester_type: str = "INTERNAL_AUTOMATED"
    scope: str
    findings: list[dict[str, Any]] = Field(default_factory=list)
    remediation_status: str = "PENDING"
    report_ref: str | None = None
    report_hash: str | None = None


class LegalReviewIn(Strict):
    reviewer_role: str
    decision: str
    jurisdiction: str = "CN"
    notes: str = ""


class OncallScheduleIn(Strict):
    name: str
    timezone: str = "Asia/Shanghai"


class OncallShiftIn(Strict):
    responder_id: str
    responder_contact: str
    role: str = "primary"
    shift_start: datetime
    shift_end: datetime


class EscalationPolicyIn(Strict):
    severity: str
    steps: list[dict[str, Any]]


class DesignPartnerProfileIn(Strict):
    profile: dict[str, Any]


class ObservationWindowIn(Strict):
    days: int = Field(default=30, ge=1, le=90)


def _finance_role(roles: tuple[str, ...]) -> None:
    if not set(roles).intersection({"owner", "finance_owner", "product_owner"}):
        raise HTTPException(403, "owner, finance_owner or product_owner role is required")




@router.get("/v1/organization")
def organization_get(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    tenant = session.get(Tenant, tid)
    users = session.scalars(select(User).where(User.tenant_id == tid).order_by(User.created_at)).all()
    return {"tenant": model_dict(tenant), "users": [model_dict(x) for x in users], "subscription": None if not active_subscription(session, tid) else model_dict(active_subscription(session, tid))}


@router.post("/v1/organization/users", status_code=201)
def organization_invite(body: UserInviteIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "admin"}): raise HTTPException(403, "owner or admin role is required")
    try:
        row = invite_user(session, tid, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.patch("/v1/organization/users/{user_id}/role")
def organization_user_role(user_id: str, body: UserRoleIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "admin"}): raise HTTPException(403, "owner or admin role is required")
    try:
        row = update_user_role(session, tid, user_id, actor, role=body.role); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/plans")
def plans(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    rows = ensure_plan_catalog(session, tid)
    return [model_dict(x) for x in rows]


@router.get("/v1/commercial/subscription")
def subscription(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    row = active_subscription(session, tid)
    return None if not row else model_dict(row)


@router.post("/v1/commercial/subscriptions", status_code=201)
def subscription_create(body: SubscriptionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    _finance_role(roles)
    try:
        row = create_subscription(session, tid, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/v1/commercial/subscriptions/{subscription_id}/transition")
def subscription_transition(subscription_id: str, body: TransitionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    _finance_role(roles)
    try:
        row = transition_subscription(session, tid, subscription_id, actor, body.target, provider_ref=body.provider_ref); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/v1/commercial/usage", status_code=201)
def usage_record(body: UsageIn, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    try:
        row = record_usage(session, tid, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/usage")
def usage_get(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return usage_summary(session, tid)


@router.get("/v1/commercial/usage/records")
def usage_records(limit: int = Query(default=100, ge=1, le=500), tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    rows = session.scalars(select(UsageRecord).where(UsageRecord.tenant_id == tid).order_by(UsageRecord.occurred_at.desc()).limit(limit)).all()
    return [model_dict(x) for x in rows]


@router.post("/v1/commercial/invoices", status_code=201)
def invoice_create(body: InvoiceIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    _finance_role(roles)
    try:
        row = build_invoice(session, tid, actor, body.subscription_id, tax_rate_basis_points=body.tax_rate_basis_points); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/invoices")
def invoice_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(Invoice).where(Invoice.tenant_id == tid).order_by(Invoice.created_at.desc())).all()]


@router.post("/v1/commercial/invoices/{invoice_id}/transition")
def invoice_transition(invoice_id: str, body: TransitionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    _finance_role(roles)
    try:
        row = transition_invoice(session, tid, invoice_id, actor, body.target, provider_ref=body.provider_ref, manual_evidence=body.manual_evidence); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/billing-events")
def billing_events(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(BillingEvent).where(BillingEvent.tenant_id == tid).order_by(BillingEvent.created_at.desc())).all()]


@router.post("/v1/commercial/onboardings", status_code=201)
def onboarding_create(body: OnboardingIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = create_onboarding(session, tid, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/onboardings")
def onboarding_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(CustomerOnboarding).where(CustomerOnboarding.tenant_id == tid).order_by(CustomerOnboarding.created_at.desc())).all()]


@router.patch("/v1/commercial/onboardings/{onboarding_id}/checklist")
def onboarding_checklist(onboarding_id: str, body: ChecklistIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = update_onboarding_checklist(session, tid, onboarding_id, actor, body.updates); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/v1/commercial/onboardings/{onboarding_id}/transition")
def onboarding_transition(onboarding_id: str, body: TransitionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = transition_onboarding(session, tid, onboarding_id, actor, body.target); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/onboarding-schema")
def onboarding_schema():
    return {"stages": ["DISCOVERY", "CONFIGURATION", "SHADOW", "AGENT_DRAFT", "LIVE_SEND", "COMPLETED"], "requirements": {k: list(v) for k, v in ONBOARDING_REQUIREMENTS.items()}}


@router.post("/v1/support/tickets", status_code=201)
def support_create(body: SupportIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = create_support_ticket(session, tid, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/support/tickets")
def support_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(SupportTicket).where(SupportTicket.tenant_id == tid).order_by(SupportTicket.created_at.desc())).all()]


@router.post("/v1/support/tickets/{ticket_id}/transition")
def support_update(ticket_id: str, body: SupportUpdateIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "operations_owner", "support_owner"}): raise HTTPException(403, "operations or support role is required")
    try:
        row = update_support_ticket(session, tid, ticket_id, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/v1/status/incidents", status_code=201)
def status_incident_create(body: StatusIncidentIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "operations_owner", "platform_owner"}): raise HTTPException(403, "operations or platform role is required")
    try:
        row = create_status_incident(session, tid, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/status/incidents")
def status_incident_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(ServiceStatusIncident).where(ServiceStatusIncident.tenant_id == tid).order_by(ServiceStatusIncident.started_at.desc())).all()]


@router.post("/v1/status/incidents/{incident_id}/transition")
def status_incident_update(incident_id: str, body: StatusIncidentUpdateIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "operations_owner", "platform_owner"}): raise HTTPException(403, "operations or platform role is required")
    try:
        row = update_status_incident(session, tid, incident_id, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/v1/compliance/documents", status_code=201)
def compliance_publish(body: ComplianceIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "privacy_owner", "legal_owner"}): raise HTTPException(403, "privacy or legal role is required")
    row = publish_compliance_document(session, tid, actor, **body.model_dump()); return model_dict(row)


@router.get("/v1/compliance/documents")
def compliance_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(ComplianceDocument).where(ComplianceDocument.tenant_id == tid).order_by(ComplianceDocument.document_key, ComplianceDocument.version.desc())).all()]


@router.post("/v1/compliance/documents/{document_id}/accept", status_code=201)
def compliance_accept(document_id: str, body: AgreementIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = accept_compliance_document(session, tid, actor, document_id, body.evidence); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/compliance/agreements")
def agreement_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(TenantAgreement).where(TenantAgreement.tenant_id == tid).order_by(TenantAgreement.accepted_at.desc())).all()]


@router.post("/v1/commercial/value-metrics", status_code=201)
def value_metric_create(body: ValueMetricIn, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    row = record_value_metric(session, tid, **body.model_dump()); return model_dict(row)


@router.get("/v1/commercial/value-metrics")
def value_metric_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(CustomerValueMetric).where(CustomerValueMetric.tenant_id == tid).order_by(CustomerValueMetric.metric_date.desc())).all()]


@router.get("/v1/ga/schema")
def ga_schema():
    return {"gates": {key: {"required_evidence": list(GA_EVIDENCE_REQUIREMENTS[key]), "required_roles": list(GA_REQUIRED_ROLES[key])} for key in GA_EVIDENCE_REQUIREMENTS}}


@router.post("/v1/ga/programs", status_code=201)
def ga_program_create(body: GAProgramIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    row = create_ga_program(session, tid, actor, **body.model_dump()); return model_dict(row)


@router.get("/v1/ga/programs")
def ga_program_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(GAReleaseProgram).where(GAReleaseProgram.tenant_id == tid).order_by(GAReleaseProgram.created_at.desc())).all()]


@router.post("/v1/ga/programs/{program_id}/evidence", status_code=201)
def ga_evidence_submit(program_id: str, body: GAEvidenceIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = submit_ga_evidence(session, tid, program_id, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/ga/programs/{program_id}/evidence")
def ga_evidence_list(program_id: str, gate: str | None = None, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    query = select(GAEvidence).where(GAEvidence.tenant_id == tid, GAEvidence.ga_program_id == program_id)
    if gate: query = query.where(GAEvidence.gate_key == gate.upper())
    return [model_dict(x) for x in session.scalars(query.order_by(GAEvidence.observed_at.desc())).all()]


@router.post("/v1/ga/evidence/{evidence_id}/decision")
def ga_evidence_decide(evidence_id: str, body: EvidenceDecisionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "product_owner", "security_owner", "privacy_owner", "operations_owner", "finance_owner"}): raise HTTPException(403, "accountable owner role is required")
    try:
        row = verify_ga_evidence(session, tid, evidence_id, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/v1/ga/programs/{program_id}/attestations", status_code=201)
def ga_attest(program_id: str, body: GAAttestationIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if body.role not in roles: raise HTTPException(403, f"token does not contain attestation role {body.role}")
    try:
        row = attest_ga_gate(session, tid, program_id, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/ga/programs/{program_id}/attestations")
def ga_attestations(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(GAAttestation).where(GAAttestation.tenant_id == tid, GAAttestation.ga_program_id == program_id).order_by(GAAttestation.signed_at.desc())).all()]


@router.get("/v1/ga/programs/{program_id}/gates/{gate_key}")
def ga_gate(program_id: str, gate_key: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    try: return evaluate_ga_gate(session, tid, program_id, gate_key.upper())
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/ga/programs/{program_id}/go-no-go")
def ga_report(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    try: return ga_go_no_go_report(session, tid, program_id)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


# ---------------------------------------------------------------------------
# Gap-closure endpoints (Gaps 1, 2, 5, 7, 8, 9, 10, 11)
# ---------------------------------------------------------------------------


# Gap 1 - Pricing Approval


@router.post("/v1/commercial/pricing-approvals", status_code=201)
def pricing_approval_create(body: PricingApprovalIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"finance_owner", "product_owner"}): raise HTTPException(403, "finance_owner or product_owner role is required")
    try:
        row = approve_pricing(session, tid, actor, approver_role=body.approver_role, decision=body.decision, contract_ref=body.contract_ref, notes=body.notes); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/pricing-approvals")
def pricing_approval_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(PricingApproval).where(PricingApproval.tenant_id == tid).order_by(PricingApproval.created_at.desc())).all()]


@router.get("/v1/commercial/pricing-approvals/status")
def pricing_approval_status(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return {"approved": pricing_is_approved(session, tid)}


# Gap 2 - Billing Webhook


@router.post("/v1/commercial/billing/webhook", status_code=200)
def billing_webhook(request: Request, body: dict[str, Any]):
    signature = request.headers.get("X-Webhook-Signature", "")
    tid = settings.default_tenant_id
    session = request.app.state.SessionLocal()
    try:
        set_tenant_context(session, tid)
        try:
            result = verify_billing_webhook(session, tid, body, signature); session.commit()
        except CommercialError as exc:
            session.rollback(); raise HTTPException(422, str(exc)) from exc
        return result
    finally:
        session.close()


# Gap 5 - Model Agreements


@router.post("/v1/commercial/model-agreements", status_code=201)
def model_agreement_create(body: ModelAgreementIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "platform_owner"}): raise HTTPException(403, "owner or platform_owner role is required")
    try:
        row = create_model_agreement(session, tid, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/model-agreements")
def model_agreement_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(ModelProviderAgreement).where(ModelProviderAgreement.tenant_id == tid).order_by(ModelProviderAgreement.created_at.desc())).all()]


# Gap 7 - Penetration Test Reports


@router.post("/v1/commercial/pentest-reports", status_code=201)
def pentest_report_create(body: PentestReportIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "security_owner"}): raise HTTPException(403, "owner or security_owner role is required")
    try:
        row = create_pentest_report(session, tid, actor, **body.model_dump()); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/commercial/pentest-reports")
def pentest_report_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(PenetrationTestReport).where(PenetrationTestReport.tenant_id == tid).order_by(PenetrationTestReport.created_at.desc())).all()]


# Gap 8 - Legal Review


@router.post("/v1/compliance/documents/{document_id}/legal-review", status_code=201)
def legal_review_create(document_id: str, body: LegalReviewIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"legal_owner", "privacy_owner"}): raise HTTPException(403, "legal_owner or privacy_owner role is required")
    try:
        row = approve_legal_document(session, tid, actor, document_id, reviewer_role=body.reviewer_role, decision=body.decision, jurisdiction=body.jurisdiction, notes=body.notes); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/compliance/legal-reviews")
def legal_review_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(LegalReviewApproval).where(LegalReviewApproval.tenant_id == tid).order_by(LegalReviewApproval.created_at.desc())).all()]


# Gap 9 - On-Call


@router.post("/v1/oncall/schedules", status_code=201)
def oncall_schedule_create(body: OncallScheduleIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "operations_owner"}): raise HTTPException(403, "owner or operations_owner role is required")
    try:
        row = create_schedule(session, tid, actor, **body.model_dump()); return model_dict(row)
    except (CommercialError, OnCallError) as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/oncall/schedules")
def oncall_schedule_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(OnCallSchedule).where(OnCallSchedule.tenant_id == tid).order_by(OnCallSchedule.created_at.desc())).all()]


@router.post("/v1/oncall/schedules/{schedule_id}/shifts", status_code=201)
def oncall_shift_create(schedule_id: str, body: OncallShiftIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "operations_owner"}): raise HTTPException(403, "owner or operations_owner role is required")
    try:
        row = create_shift(session, tid, actor, schedule_id=schedule_id, **body.model_dump()); return model_dict(row)
    except (CommercialError, OnCallError) as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/oncall/schedules/{schedule_id}/shifts")
def oncall_shift_list(schedule_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(OnCallShift).where(OnCallShift.tenant_id == tid, OnCallShift.schedule_id == schedule_id).order_by(OnCallShift.shift_start.desc())).all()]


@router.get("/v1/oncall/current")
def oncall_current(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in current_responder(session, tid)]


@router.post("/v1/oncall/escalation-policies", status_code=201)
def oncall_escalation_policy_create(body: EscalationPolicyIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "operations_owner"}): raise HTTPException(403, "owner or operations_owner role is required")
    try:
        row = set_escalation_policy(session, tid, actor, **body.model_dump()); return model_dict(row)
    except (CommercialError, OnCallError) as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/oncall/escalation-policies")
def oncall_escalation_policy_list(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return [model_dict(x) for x in session.scalars(select(EscalationPolicy).where(EscalationPolicy.tenant_id == tid).order_by(EscalationPolicy.created_at.desc())).all()]


@router.get("/v1/oncall/coverage")
def oncall_coverage(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    return {"covered": oncall_coverage_complete(session, tid)}


# Gap 10 - Design Partner Profile


@router.patch("/v1/commercial/onboardings/{onboarding_id}/design-partner-profile")
def design_partner_profile_update(onboarding_id: str, body: DesignPartnerProfileIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = update_design_partner_profile(session, tid, onboarding_id, actor, body.profile); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


# Gap 11 - Observation Window


@router.post("/v1/ga/programs/{program_id}/observation-window/start", status_code=201)
def observation_window_start(program_id: str, body: ObservationWindowIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"owner", "product_owner"}): raise HTTPException(403, "owner or product_owner role is required")
    try:
        row = start_observation_window(session, tid, actor, program_id, days=body.days); return model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.post("/v1/ga/programs/{program_id}/observation-window/check")
def observation_window_check(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    try:
        row = check_observation_window(session, tid, program_id); return None if not row else model_dict(row)
    except CommercialError as exc: raise HTTPException(422, str(exc)) from exc


@router.get("/v1/ga/programs/{program_id}/observation-window")
def observation_window_get(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    row = session.scalar(select(ObservationWindow).where(ObservationWindow.tenant_id == tid, ObservationWindow.ga_program_id == program_id).order_by(ObservationWindow.created_at.desc()))
    return None if not row else model_dict(row)
