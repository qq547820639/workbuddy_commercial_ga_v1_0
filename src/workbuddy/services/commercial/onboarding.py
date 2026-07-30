"""Customer onboarding, design partner profiles, value metrics and user management."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import CustomerOnboarding, CustomerValueMetric, ProductPlan
from workbuddy.services.audit import append_audit

from ._common import CommercialError, ONBOARDING_REQUIREMENTS, ONBOARDING_STAGES
from .billing import active_subscription


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


def update_design_partner_profile(session: Session, tenant_id: str, onboarding_id: str, actor_id: str, profile: dict[str, Any]) -> CustomerOnboarding:
    """Gap 10: Update the design partner profile on a customer onboarding record."""
    row = session.scalar(select(CustomerOnboarding).where(CustomerOnboarding.id == onboarding_id, CustomerOnboarding.tenant_id == tenant_id))
    if not row:
        raise CommercialError("onboarding not found")
    row.design_partner_profile = profile; row.version += 1
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="commercial.design_partner_profile_updated", aggregate_type="CustomerOnboarding", aggregate_id=row.id, aggregate_version=row.version, payload={"profile": profile})
    return row


def record_value_metric(session: Session, tenant_id: str, *, metric_date: str, metric_key: str, value: int, unit: str, source: str, dimensions: dict[str, Any] | None = None) -> CustomerValueMetric:
    row = session.scalar(select(CustomerValueMetric).where(CustomerValueMetric.tenant_id == tenant_id, CustomerValueMetric.metric_date == metric_date, CustomerValueMetric.metric_key == metric_key))
    if not row:
        row = CustomerValueMetric(tenant_id=tenant_id, metric_date=metric_date, metric_key=metric_key, value=value, unit=unit, source=source, dimensions=dimensions or {})
        session.add(row)
    else:
        row.value = value; row.unit = unit; row.source = source; row.dimensions = dimensions or {}
    session.flush(); return row


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
