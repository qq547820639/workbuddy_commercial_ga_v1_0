from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderNotConfigured(RuntimeError):
    """Raised when a payment provider is not properly configured or when a real
    provider API operation has not been implemented.

    The commercial billing layer selects a provider explicitly via
    ``Settings.billing_provider``. A configured live provider (e.g. Stripe) must
    never silently degrade to manual/offline behaviour: if it cannot honour a
    request it raises this error so the gap stays visible.
    """


@dataclass
class PaymentResult:
    """Outcome of confirming/capturing a payment at a provider."""

    success: bool
    provider_ref: str
    raw_response: dict[str, Any] = field(default_factory=dict)


class PaymentProvider(Protocol):
    """Provider-neutral payment abstraction used by the commercial billing layer.

    Implementations create provider customers and subscriptions, confirm payments
    against invoices, and verify webhook payloads. A provider that cannot honour a
    request must raise :class:`ProviderNotConfigured` rather than returning a
    simulated result.
    """

    def create_customer(self, tenant_id: str, email: str, name: str) -> str:
        """Create a customer at the provider and return its provider ``customer_ref``."""
        ...

    def create_subscription(self, customer_ref: str, plan_ref: str) -> str:
        """Create a subscription for an existing customer and return ``subscription_ref``."""
        ...

    def confirm_payment(
        self, invoice_ref: str, amount_cny_fen: int, currency: str
    ) -> PaymentResult:
        """Confirm/capture a payment for an invoice and return a :class:`PaymentResult`."""
        ...

    def verify_webhook(
        self, payload: dict[str, Any], signature: str, secret: str
    ) -> dict[str, Any]:
        """Verify a webhook signature and return the decoded payload as a dict."""
        ...
