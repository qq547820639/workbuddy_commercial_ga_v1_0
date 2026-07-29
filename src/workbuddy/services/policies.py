from __future__ import annotations

from datetime import timedelta
from email.utils import parseaddr
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import ExternalOperation, TenantPolicy
from workbuddy.settings import Settings, settings
from .common import content_hash, utcnow


class PolicyViolation(ValueError):
    pass


DEFAULT_EXTERNAL_ACTION_POLICY = {
    "require_owner_approval": True,
    "allow_bcc": False,
    "allow_attachments": False,
    "daily_send_limit": 20,
    "mission_send_limit": 3,
    "allowed_recipient_domains": [],
    "allowed_recipient_addresses": [],
}


def ensure_default_policies(session: Session, tenant_id: str, cfg: Settings = settings) -> TenantPolicy:
    row = session.scalar(select(TenantPolicy).where(TenantPolicy.tenant_id == tenant_id, TenantPolicy.policy_key == "external_email"))
    if row:
        return row
    config = dict(DEFAULT_EXTERNAL_ACTION_POLICY)
    config.update({
        "allow_bcc": cfg.allow_bcc,
        "allow_attachments": cfg.allow_attachments,
        "daily_send_limit": cfg.daily_send_limit,
        "mission_send_limit": cfg.mission_send_limit,
        "allowed_recipient_domains": list(cfg.allowed_recipient_domains),
        "allowed_recipient_addresses": list(cfg.allowed_recipient_addresses),
    })
    row = TenantPolicy(tenant_id=tenant_id, policy_key="external_email", config=config, version=1)
    session.add(row)
    session.flush()
    return row


def email_hashes(action: dict[str, Any]) -> dict[str, str]:
    recipients = {
        "to": sorted(action.get("to") or action.get("recipients") or []),
        "cc": sorted(action.get("cc") or []),
        "bcc": sorted(action.get("bcc") or []),
    }
    attachments = [
        {"name": a.get("name"), "sha256": a.get("sha256"), "size": a.get("size")}
        for a in action.get("attachments") or []
    ]
    body = {"subject": action.get("subject", ""), "text": action.get("body_text", ""), "html": action.get("body_html")}
    return {
        "recipient_hash": content_hash(recipients),
        "body_hash": content_hash(body),
        "attachment_hash": content_hash(attachments),
        "parameters_hash": content_hash(action),
    }


def validate_email_action(session: Session, tenant_id: str, mission_id: str, action: dict[str, Any], cfg: Settings = settings) -> dict[str, str]:
    policy = ensure_default_policies(session, tenant_id, cfg).config
    to = list(action.get("to") or action.get("recipients") or [])
    cc = list(action.get("cc") or [])
    bcc = list(action.get("bcc") or [])
    if not to:
        raise PolicyViolation("at least one To recipient is required")
    if bcc and not (policy.get("allow_bcc", False) and cfg.allow_bcc):
        raise PolicyViolation("BCC is disabled by deployment or tenant policy")
    if action.get("attachments") and not (policy.get("allow_attachments", False) and cfg.allow_attachments):
        raise PolicyViolation("attachments are disabled by deployment or tenant policy")
    policy_addresses = {x.lower() for x in policy.get("allowed_recipient_addresses", [])}
    policy_domains = {x.lower().lstrip("@") for x in policy.get("allowed_recipient_domains", [])}
    env_addresses = {x.lower() for x in cfg.allowed_recipient_addresses}
    env_domains = {x.lower().lstrip("@") for x in cfg.allowed_recipient_domains}
    def permitted(addr: str, domain: str, addresses: set[str], domains: set[str]) -> bool:
        return not (addresses or domains) or addr in addresses or domain in domains
    for raw in to + cc + bcc:
        addr = parseaddr(raw)[1].lower()
        domain = addr.rsplit("@", 1)[-1] if "@" in addr else ""
        if not addr:
            raise PolicyViolation(f"invalid recipient: {raw}")
        if not permitted(addr, domain, env_addresses, env_domains) or not permitted(addr, domain, policy_addresses, policy_domains):
            raise PolicyViolation(f"recipient is outside the Beta allowlist: {addr}")
    since = utcnow() - timedelta(days=1)
    daily_count = session.scalar(select(func.count()).select_from(ExternalOperation).where(
        ExternalOperation.tenant_id == tenant_id,
        ExternalOperation.operation_type.in_(["email_send", "gmail_send", "graph_send"]),
        ExternalOperation.status == "SUCCEEDED",
        ExternalOperation.created_at >= since,
        ExternalOperation.demo_mode.is_(False),
    )) or 0
    if daily_count >= min(int(policy.get("daily_send_limit", cfg.daily_send_limit)), cfg.daily_send_limit):
        raise PolicyViolation("daily live-send limit reached")
    mission_count = session.scalar(select(func.count()).select_from(ExternalOperation).where(
        ExternalOperation.tenant_id == tenant_id,
        ExternalOperation.mission_id == mission_id,
        ExternalOperation.status == "SUCCEEDED",
        ExternalOperation.demo_mode.is_(False),
    )) or 0
    if mission_count >= min(int(policy.get("mission_send_limit", cfg.mission_send_limit)), cfg.mission_send_limit):
        raise PolicyViolation("mission live-send limit reached")
    from .commercial import active_subscription, quota_allows
    if active_subscription(session, tenant_id):
        allowed, quota = quota_allows(session, tenant_id, "live_email_sends", 1)
        if not allowed:
            raise PolicyViolation(f"subscription live-email quota reached: {quota}")
    return email_hashes(action)
