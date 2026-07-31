"""Billing domain: plan catalog, pricing, subscriptions, usage, invoices and webhooks."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    BillingEvent, Invoice, PricingApproval, ProductPlan, TenantSubscription, UsageRecord,
)
from workbuddy.services.audit import append_audit
from workbuddy.services.common import content_hash, utcnow
from workbuddy.settings import settings

from ._common import CommercialError, REFERENCE_PLANS


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
        from workbuddy.services.payments.tax_engine import calculate_tax
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


def verify_billing_webhook(session: Session, tenant_id: str, payload: dict[str, Any], signature: str) -> dict[str, Any]:
    """Gap 2: Verify a billing webhook and trigger invoice payment if valid."""
    from workbuddy.services.payments import get_payment_provider
    provider = get_payment_provider(settings)
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
