#!/usr/bin/env python3
"""Gap 2: End-to-end billing dry run.

Creates (or reuses) a trial subscription, records metered usage, builds an
invoice with tax via the tax engine, simulates a webhook-driven payment, and
verifies that a duplicate webhook is handled idempotently. Prints a JSON summary
of every step so the commercial billing path can be exercised without a real
payment provider or bank settlement.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

# The manual billing provider requires a non-empty shared webhook secret to
# verify payloads. For a self-contained dry run we default one in-process before
# the settings module is imported, so an operator does not have to configure it
# just to exercise the code path.
os.environ.setdefault("WORKBUDDY_BILLING_WEBHOOK_SECRET", "billing-dry-run-secret")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import BillingEvent
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.services.billing.tax_engine import calculate_tax
from workbuddy.services.commercial import (
    active_subscription,
    build_invoice,
    create_subscription,
    record_usage,
    transition_invoice,
    verify_billing_webhook,
)
from workbuddy.settings import settings


def main() -> None:
    init_db()
    tenant_id = settings.default_tenant_id
    actor_id = "billing-dry-run"
    summary: dict = {
        "gap": 2,
        "title": "End-to-end billing dry run",
        "tenant_id": tenant_id,
        "billing_provider": settings.billing_provider,
        "steps": [],
    }

    with SessionLocal() as session:
        apply_tenant_context(session, tenant_id, local=True)

        # Step 1: trial subscription. Reuse an existing active subscription if one
        # already exists (create_subscription refuses duplicates).
        sub = active_subscription(session, tenant_id)
        if not sub:
            sub = create_subscription(
                session, tenant_id, actor_id,
                plan_key="starter", billing_cycle="monthly", trial_days=14,
                provider=settings.billing_provider,
            )
        summary["subscription"] = {
            "id": sub.id,
            "status": sub.status,
            "billing_cycle": sub.billing_cycle,
            "provider": sub.provider,
        }
        summary["steps"].append({"step": "create_subscription", "status": sub.status})

        # Step 2: record usage. Calling again with the same idempotency key must
        # return the identical record instead of double-counting.
        usage_key = f"dry-run-usage-{sub.id}-{uuid.uuid4().hex[:8]}"
        usage = record_usage(
            session, tenant_id,
            metric_key="agent_runs", quantity=5, unit="run",
            source_type="dry_run", source_id="billing-dry-run",
            idempotency_key=usage_key, cost_cny_fen=0,
        )
        usage_again = record_usage(
            session, tenant_id,
            metric_key="agent_runs", quantity=5, unit="run",
            source_type="dry_run", source_id="billing-dry-run",
            idempotency_key=usage_key, cost_cny_fen=0,
        )
        summary["usage"] = {
            "metric_key": usage.metric_key,
            "quantity": usage.quantity,
            "idempotent": usage.id == usage_again.id,
        }
        summary["steps"].append(
            {"step": "record_usage", "idempotent": usage.id == usage_again.id}
        )

        # Step 3: build an invoice with tax. Use the tax engine via tax_region.
        tax_region = settings.tax_default_region or "CN"
        _, rate_bps, tax_type = calculate_tax(0, tax_region)
        invoice = build_invoice(
            session, tenant_id, actor_id, sub.id, tax_region=tax_region,
        )
        summary["invoice"] = {
            "id": invoice.id,
            "number": invoice.invoice_number,
            "status": invoice.status,
            "subtotal_cny_fen": invoice.subtotal_cny_fen,
            "tax_cny_fen": invoice.tax_cny_fen,
            "total_cny_fen": invoice.total_cny_fen,
            "tax_type": invoice.tax_type,
            "tax_region": invoice.tax_region,
            "tax_rate_bps": rate_bps,
            "lines": invoice.lines,
        }
        summary["steps"].append(
            {"step": "build_invoice", "total_cny_fen": invoice.total_cny_fen}
        )

        # Step 4: open the draft invoice so a payment can be applied.
        before_open = invoice.status
        if invoice.status == "DRAFT":
            invoice = transition_invoice(
                session, tenant_id, invoice.id, actor_id, "OPEN",
            )
        summary["steps"].append(
            {"step": "transition_invoice_open", "from": before_open, "to": invoice.status}
        )

        # Step 5: simulate a webhook payment. The manual provider verifies the
        # signature against the shared secret and marks an OPEN invoice as PAID.
        webhook_payload = {
            "invoice_ref": invoice.invoice_number,
            "event": "invoice.payment_succeeded",
            "amount_cny_fen": invoice.total_cny_fen,
            "currency": "CNY",
        }
        webhook_signature = settings.billing_webhook_secret
        first_webhook = verify_billing_webhook(
            session, tenant_id, webhook_payload, webhook_signature,
        )

        # Step 6: replay the exact same webhook. The invoice is now PAID, so the
        # second call must be a safe no-op rather than a duplicate payment. The
        # real idempotency guarantee is that the deduplicating BillingEvent
        # (keyed on invoice:<id>:webhook_paid) is recorded exactly once even
        # after the webhook is replayed.
        webhook_event_key = f"invoice:{invoice.id}:webhook_paid"
        events_after_first = session.scalar(
            select(func.count()).select_from(BillingEvent).where(
                BillingEvent.tenant_id == tenant_id,
                BillingEvent.idempotency_key == webhook_event_key,
            )
        ) or 0

        second_webhook = verify_billing_webhook(
            session, tenant_id, webhook_payload, webhook_signature,
        )
        events_after_second = session.scalar(
            select(func.count()).select_from(BillingEvent).where(
                BillingEvent.tenant_id == tenant_id,
                BillingEvent.idempotency_key == webhook_event_key,
            )
        ) or 0

        webhook_idempotent = (
            events_after_first == 1 and events_after_second == 1
        )
        summary["webhook"] = {
            "first": first_webhook,
            "second": second_webhook,
            "billing_events_after_first": events_after_first,
            "billing_events_after_second": events_after_second,
            "idempotent": webhook_idempotent,
        }
        summary["steps"].append(
            {"step": "verify_billing_webhook", "idempotent": webhook_idempotent}
        )

        # Refresh the invoice status after the webhook flow.
        session.refresh(invoice)
        summary["invoice"]["status"] = invoice.status
        summary["invoice"]["paid_at"] = (
            invoice.paid_at.isoformat() if invoice.paid_at else None
        )

        session.commit()

    summary["ok"] = (
        summary["usage"]["idempotent"]
        and summary["webhook"]["idempotent"]
        and summary["invoice"]["status"] == "PAID"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
