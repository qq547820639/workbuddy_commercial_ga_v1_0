from __future__ import annotations

import argparse
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import OutboxEvent, Tenant
from workbuddy.db.session import SessionLocal, apply_tenant_context, clear_tenant_context
from .common import utcnow


def publish_batch(session: Session, limit: int = 100, fail_event_type: str | None = None, tenant_id: str | None = None) -> dict[str, int]:
    query = select(OutboxEvent).where(OutboxEvent.published_at.is_(None), OutboxEvent.dead_lettered.is_(False))
    if tenant_id:
        query = query.where(OutboxEvent.tenant_id == tenant_id)
    rows = session.scalars(
        query
        .order_by(OutboxEvent.occurred_at.asc())
        .limit(limit)
    ).all()
    published = failed = 0
    for row in rows:
        try:
            if fail_event_type and row.event_type == fail_event_type:
                raise RuntimeError("simulated publisher failure")
            # Internal Alpha: stdout/log transport. Replace with broker adapter in production.
            row.published_at = utcnow()
            row.attempts += 1
            row.last_error = None
            published += 1
        except Exception as exc:  # pragma: no cover - exercised through tests with deterministic branch
            row.attempts += 1
            row.last_error = str(exc)
            if row.attempts >= 5:
                row.dead_lettered = True
            failed += 1
    session.commit()
    return {"published": published, "failed": failed}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    with SessionLocal() as catalog_session:
        tenants = catalog_session.scalars(select(Tenant.id).where(Tenant.status == "active")).all()
    for tenant_id in tenants:
        with SessionLocal() as session:
            try:
                apply_tenant_context(session, tenant_id, local=False)
                print({"tenant_id": tenant_id, **publish_batch(session, args.limit, tenant_id=tenant_id)})
            finally:
                clear_tenant_context(session)
                session.commit()
