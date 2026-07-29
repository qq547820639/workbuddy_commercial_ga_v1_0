from __future__ import annotations

import uuid
from typing import Any

from .base import PaymentResult


class ManualProvider:
    """Manual/offline payment provider used for pilots, dry-runs and gap closure.

    This wraps the existing manual billing behaviour: every provider object is
    simulated with a deterministic ``manual-{uuid}`` reference and
    :meth:`confirm_payment` always succeeds with manual evidence.

    The manual provider must only be selected deliberately (via
    ``Settings.billing_provider == "manual"``); it must never be used as a silent
    fallback for a misconfigured live provider.
    """

    _PROVIDER = "manual"

    def create_customer(self, tenant_id: str, email: str, name: str) -> str:
        return f"manual-customer-{uuid.uuid4()}"

    def create_subscription(self, customer_ref: str, plan_ref: str) -> str:
        return f"manual-subscription-{uuid.uuid4()}"

    def confirm_payment(
        self, invoice_ref: str, amount_cny_fen: int, currency: str
    ) -> PaymentResult:
        provider_ref = f"manual-payment-{uuid.uuid4()}"
        return PaymentResult(
            success=True,
            provider_ref=provider_ref,
            raw_response={
                "provider": self._PROVIDER,
                "invoice_ref": invoice_ref,
                "amount_cny_fen": amount_cny_fen,
                "currency": currency,
                "status": "succeeded",
                "manual_evidence": True,
            },
        )

    def verify_webhook(
        self, payload: dict[str, Any], signature: str, secret: str
    ) -> dict[str, Any]:
        # When a shared secret is configured, the signature must match it.
        # When no secret is configured (pilot/dry-run), accept any non-empty
        # signature so the manual provider can simulate webhook flows end-to-end.
        if secret:
            if signature != secret:
                raise ValueError("manual webhook signature does not match shared secret")
        elif not signature:
            raise ValueError("manual webhook requires a signature or shared secret")
        return payload
