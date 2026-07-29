from __future__ import annotations
from typing import Any
import httpx
from sqlalchemy.orm import Session
from workbuddy.services.oncall import current_responder
from workbuddy.settings import settings
from workbuddy.services.common import utcnow

class AlertingError(RuntimeError):
    pass

def route_alert(session, tenant_id, *, severity, title, description, schedule_id=None):
    """Route an alert to the current on-call responder and fire the webhook."""
    responders = current_responder(session, tenant_id, schedule_id=schedule_id)
    if not responders:
        # No on-call responder, just fire the webhook
        pass
    primary = next((r for r in responders if r.role == "primary"), responders[0] if responders else None)
    payload = {
        "severity": severity, "title": title, "description": description,
        "tenant_id": tenant_id, "timestamp": utcnow().isoformat(),
        "responder": {"id": primary.responder_id, "contact": primary.responder_contact, "role": primary.role} if primary else None,
    }
    if settings.alert_webhook_url:
        try:
            response = httpx.post(settings.alert_webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            return {"delivered": True, "status_code": response.status_code, "responder": payload["responder"]}
        except Exception as exc:
            return {"delivered": False, "error": str(exc), "responder": payload["responder"]}
    return {"delivered": False, "error": "no alert webhook configured", "responder": payload["responder"]}
