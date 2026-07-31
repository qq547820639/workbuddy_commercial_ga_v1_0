from __future__ import annotations

from .base import PaymentProvider, ProviderNotConfigured, PaymentResult
from .manual import ManualProvider
from .tax_engine import TaxRateTable, calculate_tax, DEFAULT_TAX_RATES
from .stripe import StripeProvider


def get_payment_provider(cfg) -> PaymentProvider:
    name = (cfg.billing_provider or "manual").lower()
    if name == "manual":
        return ManualProvider()
    if name == "stripe":
        return StripeProvider(cfg)
    return ManualProvider()


# Backward-compatible alias; remove after all callers migrated.
get_billing_provider = get_payment_provider
