from __future__ import annotations

import json
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.connectors.microsoft_graph import MicrosoftGraphConnector
from workbuddy.db.models import MailAccount, MailMessage, SyncRun
from .audit import append_audit
from .business import ingest_mail
from .common import utcnow


class MailSyncError(RuntimeError):
    pass


def sync_graph_folder(
    session: Session,
    tenant_id: str,
    account: MailAccount,
    *,
    folder_id: str = "inbox",
    connector: MicrosoftGraphConnector | None = None,
) -> SyncRun:
    if account.provider != "graph" or account.tenant_id != tenant_id:
        raise MailSyncError("Microsoft Graph account does not belong to this tenant")
    graph = connector or MicrosoftGraphConnector()
    cursor_map = json.loads(account.cursor or "{}") if (account.cursor or "").startswith("{") else {}
    run = SyncRun(
        tenant_id=tenant_id,
        account_id=account.id,
        provider="graph",
        sync_type="delta",
        status="RUNNING",
        cursor_before=cursor_map.get(folder_id),
    )
    session.add(run)
    session.flush()
    account.sync_status = "running"
    try:
        token = graph.valid_access_token(session, account)
        url = cursor_map.get(folder_id)
        created = reused = deleted = 0
        while True:
            data = graph.delta(token, folder_id=folder_id, cursor_url=url)
            for raw in data.get("value", []):
                provider_id = f"graph:{raw.get('id', '')}"
                if "@removed" in raw:
                    existing = session.scalar(select(MailMessage).where(
                        MailMessage.tenant_id == tenant_id,
                        MailMessage.provider_message_id == provider_id,
                    ))
                    if existing and not existing.provider_deleted:
                        existing.provider_deleted = True
                        existing.processing_status = "PROVIDER_DELETED"
                        deleted += 1
                        append_audit(session, tenant_id=tenant_id, actor_type="service", actor_id="graph-delta-sync",
                                     action="mail.message_provider_deleted", aggregate_type="mail_message", aggregate_id=existing.id,
                                     payload={"provider_message_id": existing.provider_message_id, "folder_id": folder_id})
                    continue
                normalized = graph.normalize_message(raw)
                normalized["labels"] = [folder_id]
                normalized["direction"] = "outbound" if folder_id.lower() in {"sentitems", "sent items", "sent"} else "inbound"
                before = session.scalar(select(MailMessage).where(
                    MailMessage.tenant_id == tenant_id,
                    MailMessage.provider_message_id == normalized["provider_message_id"],
                ))
                message = ingest_mail(session, tenant_id, normalized, actor="graph-delta-sync")
                message.account_id = account.id
                created += 0 if before else 1
                reused += 1 if before else 0
            if data.get("@odata.nextLink"):
                url = data["@odata.nextLink"]
                continue
            cursor_map[folder_id] = data.get("@odata.deltaLink") or url
            break
        account.cursor = json.dumps(cursor_map)
        account.sync_status = "idle"
        account.status = "active"
        account.last_synced_at = utcnow()
        account.last_error = None
        run.status = "SUCCEEDED"
        run.cursor_after = cursor_map.get(folder_id)
        run.created_count = created
        run.reused_count = reused
        run.deleted_count = deleted
        run.finished_at = utcnow()
        return run
    except Exception as exc:
        account.sync_status = "error"
        account.status = "error"
        account.last_error = str(exc)
        run.status = "FAILED"
        run.error = str(exc)
        run.finished_at = utcnow()
        raise MailSyncError(str(exc)) from exc
