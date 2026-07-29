from __future__ import annotations
from datetime import datetime, timedelta
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from workbuddy.db.models import OnCallSchedule, OnCallShift, EscalationPolicy
from workbuddy.services.audit import append_audit
from workbuddy.services.common import content_hash, naive_utc, utcnow

class OnCallError(ValueError):
    pass

def create_schedule(session, tenant_id, actor_id, *, name, timezone="Asia/Shanghai"):
    existing = session.scalar(select(OnCallSchedule).where(OnCallSchedule.tenant_id == tenant_id, OnCallSchedule.name == name))
    if existing: return existing
    row = OnCallSchedule(tenant_id=tenant_id, name=name, timezone=timezone)
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="oncall.schedule_created", aggregate_type="OnCallSchedule", aggregate_id=row.id, payload={"name": name})
    return row

def create_shift(session, tenant_id, actor_id, *, schedule_id, responder_id, responder_contact, role="primary", shift_start, shift_end):
    row = OnCallShift(tenant_id=tenant_id, schedule_id=schedule_id, responder_id=responder_id, responder_contact=responder_contact, role=role, shift_start=shift_start, shift_end=shift_end)
    session.add(row); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="oncall.shift_created", aggregate_type="OnCallShift", aggregate_id=row.id, payload={"responder_id": responder_id, "role": role})
    return row

def current_responder(session, tenant_id, schedule_id=None):
    now = naive_utc(utcnow())
    query = select(OnCallShift).where(OnCallShift.tenant_id == tenant_id, OnCallShift.shift_start <= now, OnCallShift.shift_end > now)
    if schedule_id: query = query.where(OnCallShift.schedule_id == schedule_id)
    return session.scalars(query.order_by(OnCallShift.role).limit(2)).all()

def set_escalation_policy(session, tenant_id, actor_id, *, severity, steps):
    if severity not in {"P0","P1","P2","P3"}: raise OnCallError("severity must be P0-P3")
    row = session.scalar(select(EscalationPolicy).where(EscalationPolicy.tenant_id == tenant_id, EscalationPolicy.severity == severity))
    if not row:
        row = EscalationPolicy(tenant_id=tenant_id, severity=severity, steps=steps)
        session.add(row)
    else:
        row.steps = steps
    session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="oncall.escalation_policy_set", aggregate_type="EscalationPolicy", aggregate_id=row.id, payload={"severity": severity})
    return row

def escalation_target(session, tenant_id, severity, elapsed_minutes=0):
    policy = session.scalar(select(EscalationPolicy).where(EscalationPolicy.tenant_id == tenant_id, EscalationPolicy.severity == severity))
    if not policy: return None
    for step in policy.steps:
        if elapsed_minutes >= int(step.get("wait_minutes", 0)):
            return step.get("notify")
    return None

def oncall_coverage_complete(session, tenant_id, *, days=7):
    """Check that there are no gaps in on-call coverage for the next N days."""
    now = naive_utc(utcnow())
    end = now + timedelta(days=days)
    shifts = session.scalars(select(OnCallShift).where(OnCallShift.tenant_id == tenant_id, OnCallShift.shift_end > now, OnCallShift.shift_start < end).order_by(OnCallShift.shift_start)).all()
    if not shifts: return False
    # Check for primary coverage gaps
    primary_shifts = [s for s in shifts if s.role == "primary"]
    if not primary_shifts: return False
    cursor = now
    for shift in primary_shifts:
        if naive_utc(shift.shift_start) > cursor: return False  # gap found
        cursor = max(cursor, naive_utc(shift.shift_end))
        if cursor >= end: return True
    return cursor >= end
