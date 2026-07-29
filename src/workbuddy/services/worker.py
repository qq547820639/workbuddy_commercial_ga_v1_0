from __future__ import annotations

import os
import time
from datetime import timedelta

from sqlalchemy import select

from workbuddy.connectors.gmail import GmailConnector
from workbuddy.connectors.microsoft_graph import MicrosoftGraphConnector
from workbuddy.db.models import AgentRun, MailAccount, Tenant
from workbuddy.db.session import SessionLocal, apply_tenant_context, clear_tenant_context, init_db
from workbuddy.domain.state_machine import AgentRunStatus
from workbuddy.settings import settings
from .executor import execute_agent_run
from .outbox import publish_batch
from .scheduler import scheduler_tick
from .common import utcnow
from .mail_sync import sync_graph_folder


def worker_tick(session, tenant_id: str, *, max_runs: int = 10) -> dict:
    result = {"tenant_id": tenant_id, "outbox": {}, "scheduler": {}, "agent_runs_executed": 0, "agent_runs_failed": 0, "watches_renewed": 0, "graph_subscriptions_renewed": 0, "graph_syncs": 0, "errors": []}
    result["outbox"] = publish_batch(session, tenant_id=tenant_id)
    result["scheduler"] = scheduler_tick(session, tenant_id)
    runs = session.scalars(select(AgentRun).where(
        AgentRun.tenant_id == tenant_id,
        AgentRun.status == AgentRunStatus.RUNNING.value,
        AgentRun.output.is_(None),
    ).order_by(AgentRun.created_at).limit(max_runs)).all()
    for run in runs:
        try:
            finished = execute_agent_run(session, tenant_id, run.id)
            if (finished.close_reason or "").startswith("failed:"):
                result["agent_runs_failed"] += 1
                result["errors"].append({"agent_run_id": run.id, "error": (finished.output or {}).get("error", finished.close_reason)})
            else:
                result["agent_runs_executed"] += 1
            session.commit()
        except Exception as exc:
            session.rollback()
            result["errors"].append({"agent_run_id": run.id, "error": str(exc)})
    if settings.gmail_topic_name:
        gmail = GmailConnector()
        threshold = utcnow() + timedelta(hours=24)
        accounts = session.scalars(select(MailAccount).where(
            MailAccount.tenant_id == tenant_id,
            MailAccount.provider == "gmail",
            MailAccount.status == "active",
        )).all()
        for account in accounts:
            expires = account.watch_expires_at
            if expires and expires.tzinfo is None:
                from datetime import timezone
                expires = expires.replace(tzinfo=timezone.utc)
            if expires and expires > threshold:
                continue
            try:
                token = gmail.valid_access_token(session, account)
                watch = gmail.register_watch(token, settings.gmail_topic_name)
                account.cursor = str(watch.get("historyId", account.cursor or "")) or account.cursor
                if watch.get("expiration"):
                    from datetime import datetime, timezone
                    account.watch_expires_at = datetime.fromtimestamp(int(watch["expiration"]) / 1000, tz=timezone.utc)
                result["watches_renewed"] += 1
                session.commit()
            except Exception as exc:
                session.rollback()
                result["errors"].append({"mail_account_id": account.id, "error": str(exc)})
    graph = MicrosoftGraphConnector()
    graph_accounts = session.scalars(select(MailAccount).where(
        MailAccount.tenant_id == tenant_id,
        MailAccount.provider == "graph",
        MailAccount.status.in_(["active", "subscription_attention", "error"]),
    )).all()
    for account in graph_accounts:
        try:
            token = graph.valid_access_token(session, account)
            expires = account.watch_expires_at
            if expires and expires.tzinfo is None:
                from datetime import timezone
                expires = expires.replace(tzinfo=timezone.utc)
            if account.provider_subscription_id and (not expires or expires <= threshold):
                renewed = graph.renew_subscription(token, account.provider_subscription_id)
                if renewed.get("expirationDateTime"):
                    from datetime import datetime
                    account.watch_expires_at = datetime.fromisoformat(renewed["expirationDateTime"].replace("Z", "+00:00"))
                account.status = "active"
                account.last_error = None
                result["graph_subscriptions_renewed"] += 1
                session.commit()
            if account.sync_status == "pending":
                sync_graph_folder(session, tenant_id, account, folder_id="inbox", connector=graph)
                result["graph_syncs"] += 1
                session.commit()
        except Exception as exc:
            session.rollback()
            result["errors"].append({"mail_account_id": account.id, "provider": "graph", "error": str(exc)})
    return result


def main() -> None:
    init_db()
    once = os.getenv("WORKBUDDY_WORKER_ONCE", "").lower() in {"1", "true", "yes"}
    while True:
        with SessionLocal() as catalog_session:
            tenant_ids = catalog_session.scalars(select(Tenant.id).where(Tenant.status == "active")).all()
        for tenant_id in tenant_ids:
            with SessionLocal() as session:
                try:
                    # Worker commits several times per tick, so use a session-level setting
                    # and explicitly clear it before the pooled connection is returned.
                    apply_tenant_context(session, tenant_id, local=False)
                    print(worker_tick(session, tenant_id), flush=True)
                finally:
                    clear_tenant_context(session)
                    session.commit()
        if once:
            return
        time.sleep(settings.worker_poll_seconds)
