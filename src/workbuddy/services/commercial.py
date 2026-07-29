from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    BillingEvent, ComplianceDocument, CustomerOnboarding, CustomerValueMetric,
    GAAttestation, GAEvidence, GAReleaseProgram, Invoice, LegalReviewApproval,
    ModelProviderAgreement, ObservationWindow, PenetrationTestReport, PilotIncident,
    PricingApproval, ProductPlan, ServiceStatusIncident, SupportTicket, TenantAgreement,
    TenantSubscription, UsageRecord,
)
from workbuddy.services.audit import append_audit
from workbuddy.services.common import content_hash, naive_utc, utcnow
from workbuddy.services.pilot import go_no_go_report
from workbuddy.settings import settings


class CommercialError(ValueError):
    pass


REFERENCE_PLANS: dict[str, dict[str, Any]] = {
    "starter": {
        "name": "Starter（参考方案）", "monthly_price_cny_fen": 99_900, "annual_price_cny_fen": 999_000,
        "entitlements": {"mailboxes": 3, "users": 5, "agent_runs": 500, "live_email_sends": 200, "model_cost_cny_fen": 30_000},
        "overage_rates": {"mailboxes": 20_000, "agent_runs": 100, "live_email_sends": 50, "model_cost_cny_fen": 1},
    },
    "growth": {
        "name": "Growth（参考方案）", "monthly_price_cny_fen": 299_900, "annual_price_cny_fen": 2_999_000,
        "entitlements": {"mailboxes": 15, "users": 30, "agent_runs": 3_000, "live_email_sends": 1_500, "model_cost_cny_fen": 150_000},
        "overage_rates": {"mailboxes": 15_000, "agent_runs": 80, "live_email_sends": 40, "model_cost_cny_fen": 1},
    },
    "scale": {
        "name": "Scale（参考方案）", "monthly_price_cny_fen": 799_900, "annual_price_cny_fen": 7_999_000,
        "entitlements": {"mailboxes": 60, "users": 150, "agent_runs": 15_000, "live_email_sends": 8_000, "model_cost_cny_fen": 600_000},
        "overage_rates": {"mailboxes": 10_000, "agent_runs": 60, "live_email_sends": 30, "model_cost_cny_fen": 1},
    },
}

ONBOARDING_STAGES = ("DISCOVERY", "CONFIGURATION", "SHADOW", "AGENT_DRAFT", "LIVE_SEND", "COMPLETED")
ONBOARDING_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "CONFIGURATION": ("business_owner_assigned", "data_inventory_complete", "approval_matrix_approved"),
    "SHADOW": ("teams_published", "skills_published", "mailboxes_connected", "security_review_complete"),
    "AGENT_DRAFT": ("gate_b_ready", "shadow_days_complete"),
    "LIVE_SEND": ("gate_c_ready", "owner_training_complete", "support_ready"),
    "COMPLETED": ("gate_d_ready", "production_open", "handover_complete", "tenant_exit_explained"),
}

SLA_HOURS = {"P0": 1, "P1": 4, "P2": 24, "P3": 72}

GA_EVIDENCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "COMMERCIAL": ("billing_dry_run", "onboarding_rehearsal", "support_sla_drill", "legal_documents_published", "tenant_exit_drill"),
    "VALUE": ("design_partner_results", "weekly_active_rate", "artifact_adoption_rate", "time_saved", "conversion_rate", "unit_economics"),
    "GA": ("production_open_go", "penetration_test_current", "privacy_legal_approval", "thirty_day_no_p0_p1", "support_oncall_ready", "customer_exit_verified"),
}
GA_REQUIRED_ROLES: dict[str, tuple[str, ...]] = {
    "COMMERCIAL": ("product_owner", "finance_owner", "operations_owner", "privacy_owner"),
    "VALUE": ("product_owner", "business_owner", "finance_owner"),
    "GA": ("product_owner", "platform_owner", "security_owner", "privacy_owner", "operations_owner", "finance_owner"),
}


def ensure_plan_catalog(session: Session, tenant_id: str) -> list[ProductPlan]:
    plans: list[ProductPlan] = []
    for key, spec in REFERENCE_PLANS.items():
        row = session.scalar(select(ProductPlan).where(ProductPlan.tenant_id == tenant_id, ProductPlan.plan_key == key, ProductPlan.version == 1))
        config = {**spec, "currency": "CNY", "pricing_status": "APPROVED" if settings.commercial_pricing_approved else "REFERENCE_ONLY_UNTIL_COMMERCIAL_APPROVAL"}
        if not row:
            row = ProductPlan(
                tenant_id=tenant_id, plan_key=key, name=spec["name"], status="ACTIVE", currency="CNY",
                monthly_price_cny_fen=spec["monthly_price_cny_fen"], annual_price_cny_fen=spec["annual_price_cny_fen"],
                entitlements={**spec["entitlements"], "pricing_status": "APPROVED" if settings.commercial_pricing_approved else "REFERENCE_ONLY_UNTIL_COMMERCIAL_APPROVAL"},
                overage_rates=spec["overage_rates"], version=1, content_hash=content_hash(config),
            )
            session.add(row); session.flush()
        plans.append(row)
    return plans


def active_subscription(session: Session, tenant_id: str) -> TenantSubscription | None:
    return session.scalar(select(TenantSubscription).where(
        TenantSubscription.tenant_id == tenant_id,
        TenantSubscription.status.in_(["TRIALING", "ACTIVE", "PAST_DUE"]),
    ).order_by(TenantSubscription.created_at.desc()))


def create_subscription(session: Session, tenant_id: str, actor_id: str, *, plan_key: str, billing_cycle: str = "monthly", trial_days: int = 14, provider: str = "manual") -> TenantSubscription:
    if billing_cycle not in {"monthly", "annual"}:
        raise CommercialError("billing_cycle must be monthly or annual")
    ensure_plan_catalog(session, tenant_id)
    plan = session.scalar(select(ProductPlan).where(ProductPlan.tenant_id == tenant_id, ProductPlan.plan_key == plan_key, ProductPlan.status == "ACTIVE").order_by(ProductPlan.version.desc()))
    if not plan:
        raise CommercialError("plan not found")
    existing = active_subscription(session, tenant_id)
    if existing and existing.status in {"TRIALING", "ACTIVE", "PAST_DUE"}:
        raise CommercialError("tenant already has an active subscription")
    now = utcnow(); period_days = 365 if billing_cycle == "annual" else 30
    row = TenantSubscription(
        tenant_id=tenant_id, plan_id=plan.id, status="TRIALING" if trial_days > 0 else "ACTIVE",
        billing_cycle=billing_cycle, current_period_start=now, current_period_end=now + timedelta(days=period_days),
        trial_ends_at=now + timedelta(days=trial_days) if trial_days > 0 else None, provider=provider,
        metadata_json={"created_by": actor_id, "pricing_status": "APPROVED" if settings.commercial_pricing_approved else "REFERENCE_ONLY_UNTIL_COMMERCIAL_APPROVAL"},
    )
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.subscription_created", aggregate_type="TenantSubscription", aggregate_id=row.id, payload={"plan_key": plan_key, "billing_cycle": billing_cycle, "status": row.status})
    return row


def transition_subscription(session: Session, tenant_id: str, subscription_id: str, actor_id: str, target: str, *, provider_ref: str | None = None) -> TenantSubscription:
    row = session.scalar(select(TenantSubscription).where(TenantSubscription.id == subscription_id, TenantSubscription.tenant_id == tenant_id))
    if not row:
        raise CommercialError("subscription not found")
    allowed = {
        "TRIALING": {"ACTIVE", "CANCELLED"}, "ACTIVE": {"PAST_DUE", "CANCELLED"},
        "PAST_DUE": {"ACTIVE", "CANCELLED"}, "CANCELLED": set(),
    }
    if target not in allowed.get(row.status, set()):
        raise CommercialError(f"invalid subscription transition {row.status} -> {target}")
    if target == "ACTIVE":
        if not settings.commercial_pricing_approved and not pricing_is_approved(session, tenant_id):
            raise CommercialError("commercial pricing has not been approved by an accountable owner")
        if not provider_ref:
            raise CommercialError("contract or payment provider confirmation reference is required to activate a paid subscription")
    before = row.status; row.status = target; row.version += 1
    if provider_ref:
        row.provider_subscription_ref = provider_ref
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.subscription_transitioned", aggregate_type="TenantSubscription", aggregate_id=row.id, aggregate_version=row.version, payload={"from": before, "to": target, "provider_ref": provider_ref})
    return row


def record_usage(session: Session, tenant_id: str, *, metric_key: str, quantity: int, unit: str, source_type: str, source_id: str, idempotency_key: str, cost_cny_fen: int = 0, dimensions: dict[str, Any] | None = None) -> UsageRecord:
    if quantity < 0 or cost_cny_fen < 0:
        raise CommercialError("usage quantity and cost cannot be negative")
    existing = session.scalar(select(UsageRecord).where(UsageRecord.tenant_id == tenant_id, UsageRecord.idempotency_key == idempotency_key))
    if existing:
        return existing
    subscription = active_subscription(session, tenant_id)
    row = UsageRecord(
        tenant_id=tenant_id, subscription_id=subscription.id if subscription else None,
        metric_key=metric_key, quantity=quantity, unit=unit, cost_cny_fen=cost_cny_fen,
        source_type=source_type, source_id=source_id, idempotency_key=idempotency_key,
        dimensions=dimensions or {},
    )
    session.add(row); session.flush()
    return row


def usage_summary(session: Session, tenant_id: str, *, period_start: datetime | None = None, period_end: datetime | None = None) -> dict[str, Any]:
    sub = active_subscription(session, tenant_id)
    start = period_start or (sub.current_period_start if sub else datetime(1970, 1, 1, tzinfo=timezone.utc))
    end = period_end or (sub.current_period_end if sub else utcnow() + timedelta(days=1))
    rows = session.execute(select(UsageRecord.metric_key, func.sum(UsageRecord.quantity), func.sum(UsageRecord.cost_cny_fen)).where(
        UsageRecord.tenant_id == tenant_id, UsageRecord.occurred_at >= start, UsageRecord.occurred_at < end,
    ).group_by(UsageRecord.metric_key)).all()
    usage = {key: {"quantity": int(qty or 0), "cost_cny_fen": int(cost or 0)} for key, qty, cost in rows}
    plan = session.get(ProductPlan, sub.plan_id) if sub else None
    entitlements = plan.entitlements if plan else {}
    quota = {}
    for key, included in entitlements.items():
        if not isinstance(included, int):
            continue
        consumed = usage.get(key, {}).get("quantity", 0)
        quota[key] = {"included": included, "consumed": consumed, "remaining": max(0, included - consumed), "overage": max(0, consumed - included)}
    return {"subscription": None if not sub else {"id": sub.id, "status": sub.status}, "period_start": start.isoformat(), "period_end": end.isoformat(), "usage": usage, "quota": quota}


def quota_allows(session: Session, tenant_id: str, metric_key: str, increment: int = 1) -> tuple[bool, dict[str, Any]]:
    summary = usage_summary(session, tenant_id)
    q = summary["quota"].get(metric_key)
    if not q:
        return True, {"unmetered": True}
    return q["consumed"] + increment <= q["included"], q


def build_invoice(session: Session, tenant_id: str, actor_id: str, subscription_id: str, *, tax_rate_basis_points: int = 0, tax_region: str | None = None) -> Invoice:
    sub = session.scalar(select(TenantSubscription).where(TenantSubscription.id == subscription_id, TenantSubscription.tenant_id == tenant_id))
    if not sub:
        raise CommercialError("subscription not found")
    plan = session.get(ProductPlan, sub.plan_id)
    if not plan:
        raise CommercialError("plan not found")
    existing = session.scalar(select(Invoice).where(Invoice.subscription_id == sub.id, Invoice.period_start == sub.current_period_start, Invoice.period_end == sub.current_period_end))
    if existing:
        return existing
    summary = usage_summary(session, tenant_id, period_start=sub.current_period_start, period_end=sub.current_period_end)
    base = plan.annual_price_cny_fen if sub.billing_cycle == "annual" else plan.monthly_price_cny_fen
    lines: list[dict[str, Any]] = [{"type": "base", "description": f"{plan.name} {sub.billing_cycle}", "amount_cny_fen": base}]
    subtotal = base
    for metric, quota in summary["quota"].items():
        overage = int(quota.get("overage", 0)); rate = int((plan.overage_rates or {}).get(metric, 0))
        if overage and rate:
            amount = overage * rate; subtotal += amount
            lines.append({"type": "overage", "metric_key": metric, "quantity": overage, "unit_rate_cny_fen": rate, "amount_cny_fen": amount})
    model_cost = sum(x.get("cost_cny_fen", 0) for x in summary["usage"].values())
    included_model = int((plan.entitlements or {}).get("model_cost_cny_fen", 0))
    model_overage = max(0, model_cost - included_model)
    if model_overage:
        subtotal += model_overage
        lines.append({"type": "model_cost_overage", "amount_cny_fen": model_overage})
    # Gap 2: Use tax engine when region is specified, otherwise fall back to explicit basis points.
    if tax_region:
        from workbuddy.services.billing.tax_engine import calculate_tax
        tax, rate_bps, tax_type = calculate_tax(subtotal, tax_region)
    else:
        tax = subtotal * max(0, tax_rate_basis_points) // 10_000
        rate_bps = max(0, tax_rate_basis_points)
        tax_type = "VAT"
        tax_region = settings.tax_default_region
    number = f"WB-{sub.current_period_start.strftime('%Y%m')}-{sub.id[:8]}"
    payload = {"number": number, "lines": lines, "subtotal": subtotal, "tax": tax, "total": subtotal + tax, "tax_type": tax_type, "tax_region": tax_region}
    row = Invoice(
        tenant_id=tenant_id, subscription_id=sub.id, invoice_number=number, status="DRAFT",
        period_start=sub.current_period_start, period_end=sub.current_period_end,
        subtotal_cny_fen=subtotal, tax_cny_fen=tax, total_cny_fen=subtotal + tax,
        lines=lines, tax_type=tax_type, tax_region=tax_region, content_hash=content_hash(payload),
    )
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.invoice_built", aggregate_type="Invoice", aggregate_id=row.id, payload={"invoice_number": number, "total_cny_fen": row.total_cny_fen, "status": "DRAFT"})
    return row


def transition_invoice(session: Session, tenant_id: str, invoice_id: str, actor_id: str, target: str, *, provider_ref: str | None = None, manual_evidence: bool = False) -> Invoice:
    row = session.scalar(select(Invoice).where(Invoice.id == invoice_id, Invoice.tenant_id == tenant_id))
    if not row:
        raise CommercialError("invoice not found")
    allowed = {"DRAFT": {"OPEN", "VOID"}, "OPEN": {"PAID", "VOID"}, "PAID": set(), "VOID": set()}
    if target not in allowed.get(row.status, set()):
        raise CommercialError(f"invalid invoice transition {row.status} -> {target}")
    if target == "PAID" and not (provider_ref or manual_evidence):
        raise CommercialError("payment provider reference or manual payment evidence is required")
    before = row.status; row.status = target
    if target == "PAID": row.paid_at = utcnow()
    if provider_ref: row.provider_ref = provider_ref
    event_key = f"invoice:{row.id}:{target}"
    event = session.scalar(select(BillingEvent).where(BillingEvent.tenant_id == tenant_id, BillingEvent.idempotency_key == event_key))
    if not event:
        session.add(BillingEvent(tenant_id=tenant_id, subscription_id=row.subscription_id, event_type=f"invoice_{target.lower()}", status="RECORDED", amount_cny_fen=row.total_cny_fen, provider=row.provider, provider_ref=provider_ref, idempotency_key=event_key, details={"invoice_id": row.id, "manual_evidence": manual_evidence}))
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.invoice_transitioned", aggregate_type="Invoice", aggregate_id=row.id, payload={"from": before, "to": target, "provider_ref": provider_ref, "manual_evidence": manual_evidence})
    return row


def create_onboarding(session: Session, tenant_id: str, actor_id: str, *, name: str, pilot_program_id: str | None = None, target_go_live_at: datetime | None = None) -> CustomerOnboarding:
    existing = session.scalar(select(CustomerOnboarding).where(CustomerOnboarding.tenant_id == tenant_id, CustomerOnboarding.name == name))
    if existing: return existing
    row = CustomerOnboarding(tenant_id=tenant_id, pilot_program_id=pilot_program_id, name=name, owner_id=actor_id, target_go_live_at=target_go_live_at, checklist={})
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.onboarding_created", aggregate_type="CustomerOnboarding", aggregate_id=row.id, payload={"name": name})
    return row


def update_onboarding_checklist(session: Session, tenant_id: str, onboarding_id: str, actor_id: str, updates: dict[str, Any]) -> CustomerOnboarding:
    row = session.scalar(select(CustomerOnboarding).where(CustomerOnboarding.id == onboarding_id, CustomerOnboarding.tenant_id == tenant_id))
    if not row: raise CommercialError("onboarding not found")
    row.checklist = {**(row.checklist or {}), **updates}; row.version += 1
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.onboarding_checklist_updated", aggregate_type="CustomerOnboarding", aggregate_id=row.id, aggregate_version=row.version, payload={"updates": updates})
    return row


def transition_onboarding(session: Session, tenant_id: str, onboarding_id: str, actor_id: str, target: str) -> CustomerOnboarding:
    row = session.scalar(select(CustomerOnboarding).where(CustomerOnboarding.id == onboarding_id, CustomerOnboarding.tenant_id == tenant_id))
    if not row: raise CommercialError("onboarding not found")
    if target not in ONBOARDING_STAGES: raise CommercialError("invalid onboarding stage")
    current_index = ONBOARDING_STAGES.index(row.stage); target_index = ONBOARDING_STAGES.index(target)
    if target_index != current_index + 1: raise CommercialError("onboarding can only advance one stage at a time")
    missing = [key for key in ONBOARDING_REQUIREMENTS.get(target, ()) if not (row.checklist or {}).get(key)]
    if missing: raise CommercialError("missing onboarding requirements: " + ", ".join(missing))
    before = row.stage; row.stage = target; row.version += 1
    if target == "COMPLETED": row.status = "COMPLETED"
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.onboarding_transitioned", aggregate_type="CustomerOnboarding", aggregate_id=row.id, aggregate_version=row.version, payload={"from": before, "to": target})
    return row


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


def record_value_metric(session: Session, tenant_id: str, *, metric_date: str, metric_key: str, value: int, unit: str, source: str, dimensions: dict[str, Any] | None = None) -> CustomerValueMetric:
    row = session.scalar(select(CustomerValueMetric).where(CustomerValueMetric.tenant_id == tenant_id, CustomerValueMetric.metric_date == metric_date, CustomerValueMetric.metric_key == metric_key))
    if not row:
        row = CustomerValueMetric(tenant_id=tenant_id, metric_date=metric_date, metric_key=metric_key, value=value, unit=unit, source=source, dimensions=dimensions or {})
        session.add(row)
    else:
        row.value = value; row.unit = unit; row.source = source; row.dimensions = dimensions or {}
    session.flush(); return row


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
    rows = session.scalars(select(GAEvidence).where(GAEvidence.ga_program_id == program_id, GAEvidence.gate_key == gate_key, GAEvidence.status == "VERIFIED").order_by(GAEvidence.evidence_type, GAEvidence.observed_at)).all()
    return content_hash([{"id": x.id, "type": x.evidence_type, "hash": x.content_hash, "status": x.status} for x in rows])


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
    verified_rows = session.scalars(select(GAEvidence).where(GAEvidence.ga_program_id == program_id, GAEvidence.gate_key == gate_key, GAEvidence.status == "VERIFIED").order_by(GAEvidence.observed_at.desc())).all()
    verified: dict[str, GAEvidence] = {}
    for row in verified_rows: verified.setdefault(row.evidence_type, row)
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


def invite_user(session: Session, tenant_id: str, actor_id: str, *, email: str, name: str, role: str) -> Any:
    from workbuddy.db.models import User
    normalized = email.strip().lower()
    if "@" not in normalized:
        raise CommercialError("valid email is required")
    existing = session.scalar(select(User).where(User.tenant_id == tenant_id, User.email == normalized))
    if existing:
        return existing
    subscription = active_subscription(session, tenant_id)
    if subscription:
        plan = session.get(ProductPlan, subscription.plan_id)
        limit = int((plan.entitlements or {}).get("users", 0)) if plan else 0
        count = session.scalar(select(func.count()).select_from(User).where(User.tenant_id == tenant_id)) or 0
        if limit and count >= limit:
            raise CommercialError("subscription user quota reached")
    row = User(tenant_id=tenant_id, email=normalized, name=name, role=role)
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.user_invited", aggregate_type="User", aggregate_id=row.id, payload={"email": normalized, "role": role})
    return row


def update_user_role(session: Session, tenant_id: str, user_id: str, actor_id: str, *, role: str) -> Any:
    from workbuddy.db.models import User
    row = session.scalar(select(User).where(User.id == user_id, User.tenant_id == tenant_id))
    if not row:
        raise CommercialError("user not found")
    before = row.role; row.role = role
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.user_role_updated", aggregate_type="User", aggregate_id=row.id, payload={"from": before, "to": role})
    return row


# ---------------------------------------------------------------------------
# Gap-closure service functions (migrations 0011–0019)
# ---------------------------------------------------------------------------

def catalog_content_hash(session: Session, tenant_id: str) -> str:
    """Gap 1: Aggregate content hash of all ACTIVE ProductPlans."""
    plans = session.scalars(select(ProductPlan).where(ProductPlan.tenant_id == tenant_id, ProductPlan.status == "ACTIVE").order_by(ProductPlan.plan_key)).all()
    return content_hash([{"plan_key": p.plan_key, "version": p.version, "content_hash": p.content_hash, "monthly_price_cny_fen": p.monthly_price_cny_fen, "annual_price_cny_fen": p.annual_price_cny_fen} for p in plans])


def approve_pricing(session: Session, tenant_id: str, actor_id: str, *, approver_role: str, decision: str, contract_ref: str | None = None, notes: str = "") -> PricingApproval:
    """Gap 1: Record a formal pricing approval bound to the current catalog hash."""
    if approver_role not in {"finance_owner", "product_owner"}:
        raise CommercialError("only finance_owner or product_owner can approve pricing")
    if decision not in {"APPROVED", "REJECTED"}:
        raise CommercialError("decision must be APPROVED or REJECTED")
    if decision == "APPROVED" and not contract_ref:
        raise CommercialError("contract reference is required to approve pricing")
    catalog_hash = catalog_content_hash(session, tenant_id)
    existing = session.scalar(select(PricingApproval).where(PricingApproval.tenant_id == tenant_id, PricingApproval.catalog_hash == catalog_hash))
    if existing:
        existing.decision = decision; existing.approver_role = approver_role; existing.approver_id = actor_id
        existing.contract_ref = contract_ref; existing.notes = notes; existing.effective_at = utcnow()
        row = existing
    else:
        row = PricingApproval(tenant_id=tenant_id, catalog_hash=catalog_hash, approver_role=approver_role, approver_id=actor_id, decision=decision, contract_ref=contract_ref, notes=notes)
        session.add(row)
    session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.pricing_approval", aggregate_type="PricingApproval", aggregate_id=row.id, payload={"decision": decision, "catalog_hash": catalog_hash, "contract_ref": contract_ref})
    return row


def pricing_is_approved(session: Session, tenant_id: str) -> bool:
    """Gap 1: Check if the current catalog has an APPROVED pricing record."""
    catalog_hash = catalog_content_hash(session, tenant_id)
    row = session.scalar(select(PricingApproval).where(PricingApproval.tenant_id == tenant_id, PricingApproval.catalog_hash == catalog_hash, PricingApproval.decision == "APPROVED"))
    return row is not None


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


def update_design_partner_profile(session: Session, tenant_id: str, onboarding_id: str, actor_id: str, profile: dict[str, Any]) -> CustomerOnboarding:
    """Gap 10: Update the design partner profile on a customer onboarding record."""
    row = session.scalar(select(CustomerOnboarding).where(CustomerOnboarding.id == onboarding_id, CustomerOnboarding.tenant_id == tenant_id))
    if not row:
        raise CommercialError("onboarding not found")
    row.design_partner_profile = profile; row.version += 1
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.design_partner_profile_updated", aggregate_type="CustomerOnboarding", aggregate_id=row.id, aggregate_version=row.version, payload={"profile": profile})
    return row


def verify_billing_webhook(session: Session, tenant_id: str, payload: dict[str, Any], signature: str) -> dict[str, Any]:
    """Gap 2: Verify a billing webhook and trigger invoice payment if valid."""
    from workbuddy.services.billing import get_billing_provider
    provider = get_billing_provider(settings)
    try:
        verified = provider.verify_webhook(payload, signature, settings.billing_webhook_secret)
    except Exception as exc:
        return {"verified": False, "error": str(exc)}
    invoice_ref = verified.get("invoice_ref") or payload.get("invoice_ref")
    if not invoice_ref:
        return {"verified": True, "action": "no_invoice_ref"}
    invoice = session.scalar(select(Invoice).where(Invoice.tenant_id == tenant_id, Invoice.invoice_number == invoice_ref))
    if not invoice:
        return {"verified": True, "action": "invoice_not_found"}
    if invoice.status == "OPEN":
        invoice.status = "PAID"; invoice.paid_at = utcnow()
        event_key = f"invoice:{invoice.id}:webhook_paid"
        if not session.scalar(select(BillingEvent).where(BillingEvent.tenant_id == tenant_id, BillingEvent.idempotency_key == event_key)):
            session.add(BillingEvent(tenant_id=tenant_id, subscription_id=invoice.subscription_id, event_type="invoice_webhook_paid", status="RECORDED", amount_cny_fen=invoice.total_cny_fen, provider=settings.billing_provider, provider_ref=signature[:100], idempotency_key=event_key, details={"invoice_id": invoice.id, "webhook_verified": True}))
        append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id="billing-webhook", action="commercial.invoice_paid_via_webhook", aggregate_type="Invoice", aggregate_id=invoice.id, payload={"invoice_number": invoice.invoice_number})
    return {"verified": True, "action": "invoice_paid" if invoice.status == "PAID" else "no_action", "invoice_status": invoice.status}
