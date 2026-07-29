from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.orm import Session
from workbuddy.db.models import Mission, SystemControl
from .audit import append_audit

class PausedError(ValueError): pass


def is_paused(session: Session, tenant_id: str, mission: Mission | None = None) -> str | None:
    scopes = [("company", "*")]
    if mission:
        scopes += [("team", mission.primary_team_id or ""), ("mission", mission.id)]
    for scope_type, scope_id in scopes:
        row = session.scalar(select(SystemControl).where(SystemControl.tenant_id == tenant_id, SystemControl.scope_type == scope_type, SystemControl.scope_id == scope_id, SystemControl.paused.is_(True)))
        if row: return row.reason or f"{scope_type} is paused"
    return None


def assert_not_paused(session: Session, tenant_id: str, mission: Mission | None = None) -> None:
    reason = is_paused(session, tenant_id, mission)
    if reason: raise PausedError(reason)


def set_control(session: Session, tenant_id: str, scope_type: str, scope_id: str, paused: bool, reason: str, actor_id: str) -> SystemControl:
    if scope_type not in {"company", "team", "mission"}: raise ValueError("invalid control scope")
    row = session.scalar(select(SystemControl).where(SystemControl.tenant_id == tenant_id, SystemControl.scope_type == scope_type, SystemControl.scope_id == scope_id))
    if not row:
        row = SystemControl(tenant_id=tenant_id, scope_type=scope_type, scope_id=scope_id, changed_by=actor_id)
        session.add(row)
    row.paused=paused; row.reason=reason; row.changed_by=actor_id
    session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id, action="control.changed", aggregate_type="system_control", aggregate_id=row.id, payload={"scope_type":scope_type,"scope_id":scope_id,"paused":paused,"reason":reason})
    return row
