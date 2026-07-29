#!/usr/bin/env python3
"""Gap 9: SLA compliance check.

Queries SupportTicket records and flags any that have breached their SLA:
``sla_due_at`` is in the past while the ticket is still open (status not
RESOLVED/CLOSED). The SLA budget per severity is defined by
``workbuddy.services.commercial.SLA_HOURS``. Prints a JSON report listing
breached tickets with how long they are overdue, plus a summary count.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbuddy.db.models import SupportTicket
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.services.commercial import SLA_HOURS
from workbuddy.services.common import utcnow
from workbuddy.settings import settings


OPEN_STATUSES = ("OPEN", "IN_PROGRESS", "WAITING_CUSTOMER")


def _aware_utc(value: datetime | None) -> datetime | None:
    """Normalize a datetime to timezone-aware UTC.

    SQLite returns naive datetimes while ``utcnow()`` is timezone-aware; mixing
    them raises ``TypeError``. Postgres returns aware values, so this is a safe
    no-op there.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _serialize_ticket(ticket: SupportTicket, now) -> dict:
    sla_due = _aware_utc(ticket.sla_due_at)
    overdue_seconds: int | None = None
    if sla_due:
        delta = (now - sla_due).total_seconds()
        overdue_seconds = int(delta) if delta > 0 else 0
    return {
        "id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "severity": ticket.severity,
        "status": ticket.status,
        "category": ticket.category,
        "title": ticket.title,
        "sla_due_at": sla_due.isoformat() if sla_due else None,
        "sla_hours": SLA_HOURS.get(ticket.severity),
        "assigned_to": ticket.assigned_to,
        "overdue_seconds": overdue_seconds,
        "overdue_minutes": (overdue_seconds // 60) if overdue_seconds is not None else None,
    }


def main() -> None:
    init_db()
    tenant_id = settings.default_tenant_id
    now = utcnow()

    with SessionLocal() as session:
        apply_tenant_context(session, tenant_id, local=True)

        open_tickets = session.scalars(
            select(SupportTicket).where(
                SupportTicket.tenant_id == tenant_id,
                SupportTicket.status.in_(OPEN_STATUSES),
            ).order_by(SupportTicket.sla_due_at.asc())
        ).all()

        breached = [
            _serialize_ticket(t, now) for t in open_tickets
            if _aware_utc(t.sla_due_at) and _aware_utc(t.sla_due_at) < now  # type: ignore[operator]
        ]
        at_risk = [
            _serialize_ticket(t, now) for t in open_tickets
            if _aware_utc(t.sla_due_at) and _aware_utc(t.sla_due_at) >= now  # type: ignore[operator]
        ]

    report = {
        "gap": 9,
        "title": "SLA compliance check",
        "tenant_id": tenant_id,
        "checked_at": now.isoformat(),
        "sla_hours": SLA_HOURS,
        "open_tickets": len(open_tickets),
        "breached_count": len(breached),
        "at_risk_count": len(at_risk),
        "breached_tickets": breached,
        "at_risk_tickets": at_risk,
        "ok": len(breached) == 0,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
