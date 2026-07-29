from __future__ import annotations

from datetime import datetime, timedelta, timezone
import time
from urllib.parse import urlencode
import httpx
import jwt
import json
from cryptography.fernet import Fernet
from sqlalchemy import select
from sqlalchemy.orm import Session
from workbuddy.db.models import MailAccount
from workbuddy.settings import Settings, settings

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
READ_SCOPES = "openid offline_access User.Read Mail.Read"
SEND_SCOPES = "Mail.Send"


class GraphNotConfigured(RuntimeError):
    pass


class MicrosoftGraphConnector:
    """Microsoft Graph adapter with folder-scoped delta cursors and separately gated send scope."""

    def __init__(self, cfg: Settings = settings):
        self.cfg = cfg
        self.cipher = Fernet(cfg.fernet_key)

    @property
    def configured(self):
        return bool(self.cfg.graph_client_id and self.cfg.graph_client_secret)

    @property
    def auth_root(self) -> str:
        return f"https://login.microsoftonline.com/{self.cfg.graph_tenant}/oauth2/v2.0"

    def authorization_url(self, tenant_id: str, user_id: str, enable_send: bool = False) -> str:
        if not self.configured:
            raise GraphNotConfigured("Microsoft Graph credentials are not configured")
        state = jwt.encode({"tenant_id": tenant_id, "user_id": user_id, "enable_send": enable_send}, self.cfg.app_secret, algorithm="HS256")
        scope = READ_SCOPES + (" " + SEND_SCOPES if enable_send else "")
        return f"{self.auth_root}/authorize?" + urlencode({
            "client_id": self.cfg.graph_client_id,
            "response_type": "code",
            "redirect_uri": self.cfg.graph_redirect_uri,
            "response_mode": "query",
            "scope": scope,
            "state": state,
        })

    def decode_state(self, state: str) -> dict:
        return jwt.decode(state, self.cfg.app_secret, algorithms=["HS256"])

    def exchange_code(self, code: str, enable_send: bool = False) -> dict:
        if not self.configured:
            raise GraphNotConfigured("Microsoft Graph credentials are not configured")
        response = httpx.post(f"{self.auth_root}/token", data={
            "client_id": self.cfg.graph_client_id,
            "client_secret": self.cfg.graph_client_secret,
            "code": code,
            "redirect_uri": self.cfg.graph_redirect_uri,
            "grant_type": "authorization_code",
            "scope": READ_SCOPES + (" " + SEND_SCOPES if enable_send else ""),
        }, timeout=20)
        response.raise_for_status()
        data = response.json()
        data["obtained_at"] = datetime.now(timezone.utc).isoformat()
        return data


    def refresh(self, token_payload: dict) -> dict:
        refresh_token = token_payload.get("refresh_token")
        if not refresh_token:
            raise GraphNotConfigured("Microsoft Graph refresh token is unavailable; reconnect the account")
        # Refresh only the scopes already granted. A read-only mailbox must not
        # silently request Mail.Send during token refresh.
        granted_scope = str(token_payload.get("scope") or READ_SCOPES)
        response = httpx.post(f"{self.auth_root}/token", data={
            "client_id": self.cfg.graph_client_id,
            "client_secret": self.cfg.graph_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": granted_scope,
        }, timeout=20)
        response.raise_for_status()
        refreshed = response.json()
        token_payload.update(refreshed)
        token_payload["refresh_token"] = refresh_token
        token_payload["obtained_at"] = datetime.now(timezone.utc).isoformat()
        return token_payload

    def save_credentials(self, session: Session, tenant_id: str, address: str, token_payload: dict) -> MailAccount:
        account = session.scalar(select(MailAccount).where(MailAccount.tenant_id == tenant_id, MailAccount.provider == "graph", MailAccount.address == address))
        if not account:
            account = MailAccount(tenant_id=tenant_id, provider="graph", address=address)
            session.add(account)
        account.encrypted_credentials = self.cipher.encrypt(json.dumps(token_payload).encode()).decode()
        account.scopes = str(token_payload.get("scope", READ_SCOPES)).split()
        account.send_enabled = SEND_SCOPES in account.scopes
        account.status = "active"
        return account

    def load_credentials(self, account: MailAccount) -> dict:
        if not account.encrypted_credentials:
            raise GraphNotConfigured("mail account has no credentials")
        return json.loads(self.cipher.decrypt(account.encrypted_credentials.encode()).decode())

    def valid_access_token(self, session: Session, account: MailAccount) -> str:
        payload = self.load_credentials(account)
        obtained = datetime.fromisoformat(payload.get("obtained_at", datetime.now(timezone.utc).isoformat()))
        if obtained.tzinfo is None:
            obtained = obtained.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) >= obtained + timedelta(seconds=max(int(payload.get("expires_in", 3600)) - 120, 60)):
            payload = self.refresh(payload)
            account.encrypted_credentials = self.cipher.encrypt(json.dumps(payload).encode()).decode()
            session.flush()
        return payload["access_token"]

    def profile(self, access_token: str) -> dict:
        response = httpx.get(f"{GRAPH_ROOT}/me?$select=id,displayName,mail,userPrincipalName", headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
        response.raise_for_status()
        return response.json()

    def delta(self, access_token: str, folder_id: str = "inbox", cursor_url: str | None = None) -> dict:
        url = cursor_url or f"{GRAPH_ROOT}/me/mailFolders/{folder_id}/messages/delta?$select=id,conversationId,internetMessageId,subject,from,toRecipients,receivedDateTime,body,hasAttachments"
        response = httpx.get(url, headers={"Authorization": f"Bearer {access_token}", "Prefer": 'IdType="ImmutableId"'}, timeout=30)
        response.raise_for_status()
        return response.json()


    def create_subscription(self, access_token: str, notification_url: str, client_state: str, resource: str = "me/mailFolders('inbox')/messages") -> dict:
        if not notification_url.startswith("https://"):
            raise GraphNotConfigured("Microsoft Graph webhook notification URL must use HTTPS")
        expiration = datetime.now(timezone.utc) + timedelta(hours=min(max(self.cfg.graph_subscription_hours, 1), 70))
        payload = {
            "changeType": "created,updated,deleted",
            "notificationUrl": notification_url,
            "lifecycleNotificationUrl": notification_url,
            "resource": resource,
            "expirationDateTime": expiration.isoformat().replace("+00:00", "Z"),
            "clientState": client_state,
        }
        response = httpx.post(
            f"{GRAPH_ROOT}/subscriptions",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Prefer": 'IdType="ImmutableId"'},
            json=payload, timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def renew_subscription(self, access_token: str, subscription_id: str) -> dict:
        expiration = datetime.now(timezone.utc) + timedelta(hours=min(max(self.cfg.graph_subscription_hours, 1), 70))
        response = httpx.patch(
            f"{GRAPH_ROOT}/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"expirationDateTime": expiration.isoformat().replace("+00:00", "Z")}, timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def delete_subscription(self, access_token: str, subscription_id: str) -> None:
        response = httpx.delete(
            f"{GRAPH_ROOT}/subscriptions/{subscription_id}",
            headers={"Authorization": f"Bearer {access_token}"}, timeout=30,
        )
        if response.status_code not in {204, 404}:
            response.raise_for_status()

    def send_message(self, access_token: str, action: dict) -> dict:
        message = {
            "subject": action.get("subject", ""),
            "body": {"contentType": "HTML" if action.get("body_html") else "Text", "content": action.get("body_html") or action.get("body_text") or ""},
            "toRecipients": [{"emailAddress": {"address": x}} for x in action.get("to") or action.get("recipients") or []],
            "ccRecipients": [{"emailAddress": {"address": x}} for x in action.get("cc") or []],
            "bccRecipients": [{"emailAddress": {"address": x}} for x in action.get("bcc") or []],
        }
        if action.get("attachments"):
            message["attachments"] = [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": a.get("name", "attachment"),
                "contentType": a.get("mime_type", "application/octet-stream"),
                "contentBytes": a["content_base64"],
            } for a in action["attachments"]]
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json", "Prefer": 'IdType="ImmutableId"'}
        draft = httpx.post(f"{GRAPH_ROOT}/me/messages", headers=headers, json=message, timeout=30)
        draft.raise_for_status()
        draft_data = draft.json()
        message_id = draft_data["id"]
        sent = httpx.post(f"{GRAPH_ROOT}/me/messages/{message_id}/send", headers=headers, timeout=30)
        sent.raise_for_status()
        return {"accepted": True, "status_code": sent.status_code, "id": message_id, "conversationId": draft_data.get("conversationId"), "internetMessageId": draft_data.get("internetMessageId")}

    def verify_sent(self, access_token: str, provider_message_id: str) -> dict:
        # Sending is asynchronous. Immutable IDs let us locate the same item after it moves
        # from Drafts to Sent Items. Retry briefly, then return an unverified result so the
        # ExternalOperation moves to UNKNOWN rather than sending again.
        url = f"{GRAPH_ROOT}/me/messages/{provider_message_id}?$select=id,isDraft,internetMessageId,conversationId,sentDateTime,parentFolderId"
        headers = {"Authorization": f"Bearer {access_token}", "Prefer": 'IdType="ImmutableId"'}
        last_status = None
        for delay in (0, 1, 2, 4):
            if delay:
                time.sleep(delay)
            response = httpx.get(url, headers=headers, timeout=30)
            last_status = response.status_code
            if response.status_code == 404:
                continue
            response.raise_for_status()
            data = response.json()
            if not bool(data.get("isDraft", True)):
                return {"verified": True, "provider_message_id": data.get("id"), "internet_message_id": data.get("internetMessageId"), "conversation_id": data.get("conversationId"), "sent_at": data.get("sentDateTime")}
        return {"verified": False, "provider_message_id": provider_message_id, "last_status": last_status, "reason": "sent copy was not observable before verification timeout"}

    def normalize_message(self, raw: dict) -> dict:
        sender = ((raw.get("from") or {}).get("emailAddress") or {})
        recipients = [x.get("emailAddress", {}).get("address", "") for x in raw.get("toRecipients", []) if x.get("emailAddress")]
        body = raw.get("body") or {}
        return {
            "provider_message_id": f"graph:{raw['id']}",
            "provider_thread_id": raw.get("conversationId"),
            "rfc_message_id": raw.get("internetMessageId"),
            "sender": f"{sender.get('name', '')} <{sender.get('address', '')}>".strip(),
            "recipients": recipients,
            "subject": raw.get("subject") or "(no subject)",
            "body_text": body.get("content") or "(empty message)",
            "body_html": body.get("content") if body.get("contentType", "html").lower() == "html" else None,
            "received_at": raw.get("receivedDateTime"),
            "has_attachments": bool(raw.get("hasAttachments")),
        }
