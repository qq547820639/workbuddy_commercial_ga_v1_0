from __future__ import annotations

import os
from typing import Any

import httpx

from .base import PaymentResult, ProviderNotConfigured


_STRIPE_API_BASE = "https://api.stripe.com/v1"


class StripeProvider:
    """Stripe payment provider (stub for gap closure).

    The constructor validates that a Stripe API key is configured and prepares an
    ``httpx`` client, but the real Stripe REST API calls are not implemented yet.
    Every real API operation raises :class:`ProviderNotConfigured` so that an
    incomplete integration can never silently degrade to manual/offline behaviour.

    The ``stripe_api_key`` / ``stripe_webhook_secret`` fields are added to
    :class:`workbuddy.settings.Settings` separately; until then they are read
    defensively via ``getattr`` and the matching environment variables.
    """

    def __init__(self, cfg: Any) -> None:
        # Read configuration defensively so this stub works whether or not the
        # Settings dataclass has been extended with Stripe fields.
        api_key = getattr(cfg, "stripe_api_key", "") or os.getenv(
            "WORKBUDDY_STRIPE_API_KEY", ""
        )
        if not api_key:
            raise ProviderNotConfigured(
                "Stripe provider is not configured: Settings.stripe_api_key "
                "(WORKBUDDY_STRIPE_API_KEY) is required"
            )
        self._api_key = api_key
        self._webhook_secret = getattr(cfg, "stripe_webhook_secret", "") or os.getenv(
            "WORKBUDDY_STRIPE_WEBHOOK_SECRET", ""
        )
        base_url = (
            getattr(cfg, "stripe_api_base_url", "")
            or os.getenv("WORKBUDDY_STRIPE_API_BASE_URL", "")
            or _STRIPE_API_BASE
        )
        # A real implementation issues requests through this client. It is created now
        # so configuration errors surface early; the stub methods below never send.
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30.0,
        )

    def create_customer(self, tenant_id: str, email: str, name: str) -> str:
        # POST /customers with email, name and metadata={"tenant_id": tenant_id}.
        raise ProviderNotConfigured(
            "Stripe provider is a stub: create_customer is not implemented"
        )

    def create_subscription(self, customer_ref: str, plan_ref: str) -> str:
        # POST /subscriptions with customer=customer_ref and items referencing plan_ref.
        raise ProviderNotConfigured(
            "Stripe provider is a stub: create_subscription is not implemented"
        )

    def confirm_payment(
        self, invoice_ref: str, amount_cny_fen: int, currency: str
    ) -> PaymentResult:
        # POST /invoices/{invoice_ref}/pay (or /payment_intents) via self._client.
        raise ProviderNotConfigured(
            "Stripe provider is a stub: confirm_payment is not implemented"
        )

    def verify_webhook(
        self, payload: dict[str, Any], signature: str, secret: str
    ) -> dict[str, Any]:
        # Real Stripe verification needs the raw request body and the Stripe-Signature
        # header to reconstruct the HMAC over "timestamp.payload". Returning a verified
        # dict without that would silently degrade security, so this stub fails loudly.
        raise ProviderNotConfigured(
            "Stripe provider is a stub: webhook verification is not implemented"
        )
