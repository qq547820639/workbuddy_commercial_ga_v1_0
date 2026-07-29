from __future__ import annotations

from datetime import timezone
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from workbuddy.db.models import AuditEvent, OutboxEvent
from .common import content_hash, utcnow
from .context import current_correlation_id


def _timestamp(value):
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


def append_audit(
    session: Session, *, tenant_id: str, actor_type: str, actor_id: str, action: str,
    aggregate_type: str, aggregate_id: str, aggregate_version: int = 1,
    payload: dict | None = None, correlation_id: str | None = None,
    causation_id: str | None = None, event_type: str | None = None,
) -> AuditEvent:
    if session.bind and session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:tenant_id))"), {"tenant_id": tenant_id})
    last = session.scalar(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.sequence.desc()).limit(1))
    sequence = (last.sequence + 1) if last else 1
    previous_hash = last.event_hash if last else "0" * 64
    event_id = str(uuid4()); occurred_at = utcnow()
    core = {
        "id": event_id, "tenant_id": tenant_id, "sequence": sequence,
        "actor_type": actor_type, "actor_id": actor_id, "action": action,
        "aggregate_type": aggregate_type, "aggregate_id": aggregate_id,
        "aggregate_version": aggregate_version,
        "correlation_id": correlation_id or current_correlation_id(),
        "causation_id": causation_id, "occurred_at": _timestamp(occurred_at),
        "payload": payload or {}, "previous_hash": previous_hash,
    }
    event_hash = content_hash({"previous_hash": previous_hash, "event": core})
    audit = AuditEvent(
        id=event_id, tenant_id=tenant_id, sequence=sequence, actor_type=actor_type,
        actor_id=actor_id, action=action, aggregate_type=aggregate_type,
        aggregate_id=aggregate_id, aggregate_version=aggregate_version,
        correlation_id=core["correlation_id"], causation_id=causation_id,
        occurred_at=occurred_at, payload=payload or {}, previous_hash=previous_hash,
        event_hash=event_hash,
    )
    session.add(audit)
    session.add(OutboxEvent(
        tenant_id=tenant_id, event_type=event_type or action,
        aggregate_type=aggregate_type, aggregate_id=aggregate_id,
        payload={"audit_event_id": event_id, **(payload or {})}, occurred_at=occurred_at,
    ))
    session.flush()
    return audit


def verify_audit_chain(session: Session, tenant_id: str) -> tuple[bool, str | None]:
    rows = session.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id).order_by(AuditEvent.sequence.asc())).all()
    previous = "0" * 64; expected_sequence = 1
    for event in rows:
        if event.sequence != expected_sequence:
            return False, event.id
        core = {
            "id": event.id, "tenant_id": event.tenant_id, "sequence": event.sequence,
            "actor_type": event.actor_type, "actor_id": event.actor_id,
            "action": event.action, "aggregate_type": event.aggregate_type,
            "aggregate_id": event.aggregate_id, "aggregate_version": event.aggregate_version,
            "correlation_id": event.correlation_id, "causation_id": event.causation_id,
            "occurred_at": _timestamp(event.occurred_at), "payload": event.payload,
            "previous_hash": previous,
        }
        expected = content_hash({"previous_hash": previous, "event": core})
        if event.previous_hash != previous or event.event_hash != expected:
            return False, event.id
        previous = event.event_hash; expected_sequence += 1
    return True, None
