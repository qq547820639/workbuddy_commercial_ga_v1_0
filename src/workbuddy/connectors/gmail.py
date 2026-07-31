from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.connectors.base import BaseMailConnector
from workbuddy.db.models import MailAccount


GMAIL_READ_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailNotConfigured(RuntimeError):
    pass


class GmailConnector(BaseMailConnector):
    @property
    def configured(self) -> bool:
        return bool(self.cfg.gmail_client_id and self.cfg.gmail_client_secret)

    def authorization_url(self, tenant_id: str, user_id: str, enable_send: bool = False) -> str:
        if not self.configured:
            raise GmailNotConfigured("Gmail OAuth credentials are not configured")
        state = jwt.encode({"tenant_id": tenant_id, "user_id": user_id, "enable_send": enable_send}, self.cfg.app_secret, algorithm="HS256")
        query = urlencode({
            "client_id": self.cfg.gmail_client_id,
            "redirect_uri": self.cfg.gmail_redirect_uri,
            "response_type": "code",
            "scope": " ".join([GMAIL_READ_SCOPE] + ([GMAIL_SEND_SCOPE] if enable_send else [])),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    def exchange_code(self, code: str) -> dict:
        if not self.configured:
            raise GmailNotConfigured("Gmail OAuth credentials are not configured")
        response = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code,
            "client_id": self.cfg.gmail_client_id,
            "client_secret": self.cfg.gmail_client_secret,
            "redirect_uri": self.cfg.gmail_redirect_uri,
            "grant_type": "authorization_code",
        }, timeout=20)
        response.raise_for_status()
        token = response.json()
        token["obtained_at"] = datetime.now(timezone.utc).isoformat()
        return token

    def refresh(self, token_payload: dict) -> dict:
        refresh_token = token_payload.get("refresh_token")
        if not refresh_token:
            raise GmailNotConfigured("Gmail refresh token is unavailable; reconnect the account")
        response = httpx.post("https://oauth2.googleapis.com/token", data={
            "client_id": self.cfg.gmail_client_id,
            "client_secret": self.cfg.gmail_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }, timeout=20)
        response.raise_for_status()
        refreshed = response.json()
        token_payload.update(refreshed)
        token_payload["refresh_token"] = refresh_token
        token_payload["obtained_at"] = datetime.now(timezone.utc).isoformat()
        return token_payload

    def valid_access_token(self, session: Session, account: MailAccount) -> str:
        payload = self.load_credentials(account)
        obtained = datetime.fromisoformat(payload.get("obtained_at", datetime.now(timezone.utc).isoformat()))
        if obtained.tzinfo is None:
            obtained = obtained.replace(tzinfo=timezone.utc)
        expires = int(payload.get("expires_in", 3600))
        if datetime.now(timezone.utc) >= obtained + timedelta(seconds=max(expires - 120, 60)):
            payload = self.refresh(payload)
            account.encrypted_credentials = self._encrypt(payload)
            session.flush()
        return payload["access_token"]

    def save_credentials(self, session: Session, tenant_id: str, address: str, token_payload: dict) -> MailAccount:
        encrypted = self._encrypt(token_payload)
        account = session.scalar(select(MailAccount).where(
            MailAccount.tenant_id == tenant_id,
            MailAccount.provider == "gmail",
            MailAccount.address == address,
        ))
        if not account:
            account = MailAccount(tenant_id=tenant_id, provider="gmail", address=address)
            session.add(account)
        account.encrypted_credentials = encrypted
        account.status = "active"
        account.scopes = str(token_payload.get("scope", GMAIL_READ_SCOPE)).split()
        account.send_enabled = GMAIL_SEND_SCOPE in account.scopes
        return account

    def load_credentials(self, account: MailAccount) -> dict:
        if not account.encrypted_credentials:
            raise GmailNotConfigured("mail account has no credentials")
        return json.loads(self.cipher.decrypt(account.encrypted_credentials.encode()).decode())

    def _encrypt(self, payload: dict) -> str:
        return self.cipher.encrypt(json.dumps(payload).encode()).decode()

    def profile(self, access_token: str) -> dict:
        return self._get(f"{API}/profile", access_token)

    def list_message_refs(self, access_token: str, *, query: str = "newer_than:30d", limit: int = 100) -> list[dict]:
        result: list[dict] = []
        page_token = None
        while len(result) < limit:
            params = {"q": query, "maxResults": min(100, limit - len(result))}
            if page_token:
                params["pageToken"] = page_token
            data = self._get(f"{API}/messages", access_token, params=params)
            result.extend(data.get("messages", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return result[:limit]

    def get_message(self, access_token: str, message_id: str) -> dict:
        return self._get(f"{API}/messages/{message_id}", access_token, params={"format": "full"})

    def normalize_message(self, raw: dict) -> dict:
        payload = raw.get("payload", {})
        headers = {h.get("name", "").lower(): h.get("value", "") for h in payload.get("headers", [])}
        text, html = self._extract_bodies(payload)
        received = None
        if headers.get("date"):
            try:
                received = parsedate_to_datetime(headers["date"])
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
            except Exception:
                received = None
        if received is None and raw.get("internalDate"):
            received = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=timezone.utc)
        recipients = [x.strip() for x in headers.get("to", "").split(",") if x.strip()]
        labels = list(raw.get("labelIds") or [])
        return {
            "provider_message_id": f"gmail:{raw['id']}",
            "provider_thread_id": raw.get("threadId"),
            "rfc_message_id": headers.get("message-id"),
            "sender": headers.get("from", "unknown"),
            "recipients": recipients,
            "subject": headers.get("subject", "(no subject)"),
            "body_text": text or self._decode_body(payload.get("body", {}).get("data")) or "(empty message)",
            "body_html": html,
            "received_at": received,
            "labels": labels,
            "direction": "outbound" if "SENT" in labels else "inbound",
            "has_attachments": self._has_attachments(payload),
        }

    def history_changes(self, access_token: str, start_history_id: str) -> tuple[dict[str, list[str]], str]:
        # Omitting historyTypes returns message and label changes. The current message
        # is fetched for additions/label changes; deletions are soft-marked locally.
        params = {"startHistoryId": start_history_id, "maxResults": 100}
        upsert_ids: list[str] = []
        deleted_ids: list[str] = []
        latest = start_history_id
        page_token = None
        while True:
            if page_token:
                params["pageToken"] = page_token
            data = self._get(f"{API}/history", access_token, params=params)
            latest = str(data.get("historyId", latest))
            for entry in data.get("history", []):
                for key in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                    for change in entry.get(key, []):
                        mid = change.get("message", {}).get("id")
                        if mid:
                            upsert_ids.append(mid)
                for deleted in entry.get("messagesDeleted", []):
                    mid = deleted.get("message", {}).get("id")
                    if mid:
                        deleted_ids.append(mid)
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        deleted = list(dict.fromkeys(deleted_ids))
        deleted_set = set(deleted)
        upserts = [mid for mid in dict.fromkeys(upsert_ids) if mid not in deleted_set]
        return {"upsert_ids": upserts, "deleted_ids": deleted}, latest

    def history(self, access_token: str, start_history_id: str) -> tuple[list[str], str]:
        """Backward-compatible helper returning messages that should be fetched."""
        changes, latest = self.history_changes(access_token, start_history_id)
        return changes["upsert_ids"], latest

    def register_watch(self, access_token: str, topic_name: str) -> dict:
        if not topic_name:
            raise GmailNotConfigured("WORKBUDDY_GMAIL_TOPIC_NAME is not configured")
        response = httpx.post(f"{API}/watch", headers=self._headers(access_token), json={
            "topicName": topic_name,
            "labelIds": ["INBOX"],
            "labelFilterBehavior": "INCLUDE",
        }, timeout=20)
        response.raise_for_status()
        return response.json()


    def send_message(self, access_token: str, action: dict) -> dict:
        message = EmailMessage()
        message["To"] = ", ".join(action.get("to") or action.get("recipients") or [])
        if action.get("cc"):
            message["Cc"] = ", ".join(action["cc"])
        if action.get("bcc"):
            message["Bcc"] = ", ".join(action["bcc"])
        message["Subject"] = action.get("subject", "")
        if action.get("in_reply_to"):
            message["In-Reply-To"] = action["in_reply_to"]
        if action.get("references"):
            message["References"] = action["references"]
        body_text = action.get("body_text") or ""
        body_html = action.get("body_html")
        message.set_content(body_text)
        if body_html:
            message.add_alternative(body_html, subtype="html")
        for attachment in action.get("attachments") or []:
            content = base64.b64decode(attachment["content_base64"])
            mime = attachment.get("mime_type", "application/octet-stream")
            maintype, subtype = mime.split("/", 1) if "/" in mime else ("application", "octet-stream")
            message.add_attachment(content, maintype=maintype, subtype=subtype, filename=attachment.get("name", "attachment"))
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        request_body = {"raw": raw}
        if action.get("provider_thread_id"):
            request_body["threadId"] = action["provider_thread_id"]
        response = httpx.post(f"{API}/messages/send", headers={**self._headers(access_token), "Content-Type": "application/json"}, json=request_body, timeout=30)
        response.raise_for_status()
        return response.json()

    def verify_sent(self, access_token: str, provider_message_id: str) -> dict:
        data = self.get_message(access_token, provider_message_id)
        labels = set(data.get("labelIds") or [])
        sent_label = "SENT" in labels
        return {
            "verified": sent_label,
            "provider_message_id": data.get("id"),
            "thread_id": data.get("threadId"),
            "sent_label": sent_label,
            "label_ids": sorted(labels),
            "reason": None if sent_label else "provider message exists but is not labelled SENT",
        }

    def revoke(self, token: str) -> None:
        response = httpx.post("https://oauth2.googleapis.com/revoke", params={"token": token}, timeout=20)
        response.raise_for_status()

    def _get(self, url: str, token: str, params: dict | None = None) -> dict:
        response = httpx.get(url, headers=self._headers(token), params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _has_attachments(payload: dict) -> bool:
        stack = [payload]
        while stack:
            part = stack.pop()
            if part.get("filename") and (part.get("body") or {}).get("attachmentId"):
                return True
            stack.extend(part.get("parts") or [])
        return False

    def _extract_bodies(self, payload: dict) -> tuple[str, str | None]:
        text_parts: list[str] = []
        html_parts: list[str] = []
        def walk(part: dict) -> None:
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data")
            if data and mime == "text/plain":
                text_parts.append(self._decode_body(data))
            elif data and mime == "text/html":
                html_parts.append(self._decode_body(data))
            for child in part.get("parts", []) or []:
                walk(child)
        walk(payload)
        return "\n".join(x for x in text_parts if x).strip(), "\n".join(x for x in html_parts if x).strip() or None

    @staticmethod
    def _decode_body(data: str | None) -> str:
        if not data:
            return ""
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode()).decode("utf-8", errors="replace")
