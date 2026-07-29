#!/usr/bin/env python3
from __future__ import annotations

import json
from workbuddy.db.session import SessionLocal, apply_tenant_context
from workbuddy.services.commercial import active_subscription, build_invoice
from workbuddy.services.common import model_dict
from workbuddy.settings import settings


def main() -> int:
    with SessionLocal() as session:
        apply_tenant_context(session, settings.default_tenant_id, local=True)
        subscription = active_subscription(session, settings.default_tenant_id)
        if not subscription:
            print(json.dumps({"error": "No active subscription"}, ensure_ascii=False)); return 2
        invoice = build_invoice(session, settings.default_tenant_id, "invoice-cli", subscription.id)
        session.commit(); print(json.dumps(model_dict(invoice), ensure_ascii=False, indent=2, default=str)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
