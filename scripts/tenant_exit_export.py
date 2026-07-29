#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from pathlib import Path
from sqlalchemy import select

from workbuddy.db.models import (
    AuditEvent, ComplianceDocument, CustomerOnboarding, CustomerValueMetric, Invoice,
    SupportTicket, TenantAgreement, TenantSubscription, UsageRecord,
)
from workbuddy.db.session import SessionLocal, apply_tenant_context
from workbuddy.services.common import model_dict
from workbuddy.settings import settings

MODELS = [TenantSubscription, UsageRecord, Invoice, CustomerOnboarding, SupportTicket, ComplianceDocument, TenantAgreement, CustomerValueMetric, AuditEvent]


def main() -> int:
    parser = argparse.ArgumentParser(description="Export commercial tenant records before an approved exit/deletion workflow.")
    parser.add_argument("--output", default="tenant-exit-export.json")
    args = parser.parse_args()
    with SessionLocal() as session:
        apply_tenant_context(session, settings.default_tenant_id, local=True)
        payload = {model.__tablename__: [model_dict(x) for x in session.scalars(select(model).where(model.tenant_id == settings.default_tenant_id)).all()] for model in MODELS}
    path = Path(args.output); path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print({"output": str(path), "note": "This script exports data only. It never deletes records or audit evidence."}); return 0


if __name__ == "__main__":
    raise SystemExit(main())
