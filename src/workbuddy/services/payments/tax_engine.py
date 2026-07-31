from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TaxRate:
    region: str
    rate_bps: int  # basis points, e.g. 1300 = 13%
    tax_type: str  # VAT, OUTSIDE_VAT, VAT_EXEMPT
    description: str


DEFAULT_TAX_RATES: dict[str, TaxRate] = {
    "CN": TaxRate("CN", 1300, "VAT", "China VAT 13%"),
    "HK": TaxRate("HK", 0, "OUTSIDE_VAT", "Hong Kong outside VAT scope"),
    "SG": TaxRate("SG", 900, "GST", "Singapore GST 9%"),
    "US": TaxRate("US", 0, "OUTSIDE_VAT", "US sales tax not applicable for digital services"),
    "EXEMPT": TaxRate("EXEMPT", 0, "VAT_EXEMPT", "VAT exempt"),
}


class TaxRateTable:
    def __init__(self, rates: dict[str, TaxRate] | None = None):
        self._rates = rates or DEFAULT_TAX_RATES

    def get_rate(self, region: str) -> TaxRate:
        return self._rates.get(region.upper(), self._rates.get("CN"))

    def calculate(self, subtotal_cny_fen: int, region: str) -> tuple[int, int, str]:
        rate = self.get_rate(region)
        tax = subtotal_cny_fen * rate.rate_bps // 10_000
        return tax, rate.rate_bps, rate.tax_type


def calculate_tax(subtotal_cny_fen: int, region: str = "CN") -> tuple[int, int, str]:
    return TaxRateTable().calculate(subtotal_cny_fen, region)
