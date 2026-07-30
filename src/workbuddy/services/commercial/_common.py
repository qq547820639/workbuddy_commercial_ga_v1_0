"""Shared exceptions and constants for the commercial domain package."""

from __future__ import annotations

from typing import Any


class CommercialError(ValueError):
    pass


REFERENCE_PLANS: dict[str, dict[str, Any]] = {
    "starter": {
        "name": "Starter（参考方案）", "monthly_price_cny_fen": 99_900, "annual_price_cny_fen": 999_000,
        "entitlements": {"mailboxes": 3, "users": 5, "agent_runs": 500, "live_email_sends": 200, "model_cost_cny_fen": 30_000},
        "overage_rates": {"mailboxes": 20_000, "agent_runs": 100, "live_email_sends": 50, "model_cost_cny_fen": 1},
    },
    "growth": {
        "name": "Growth（参考方案）", "monthly_price_cny_fen": 299_900, "annual_price_cny_fen": 2_999_000,
        "entitlements": {"mailboxes": 15, "users": 30, "agent_runs": 3_000, "live_email_sends": 1_500, "model_cost_cny_fen": 150_000},
        "overage_rates": {"mailboxes": 15_000, "agent_runs": 80, "live_email_sends": 40, "model_cost_cny_fen": 1},
    },
    "scale": {
        "name": "Scale（参考方案）", "monthly_price_cny_fen": 799_900, "annual_price_cny_fen": 7_999_000,
        "entitlements": {"mailboxes": 60, "users": 150, "agent_runs": 15_000, "live_email_sends": 8_000, "model_cost_cny_fen": 600_000},
        "overage_rates": {"mailboxes": 10_000, "agent_runs": 60, "live_email_sends": 30, "model_cost_cny_fen": 1},
    },
}

ONBOARDING_STAGES = ("DISCOVERY", "CONFIGURATION", "SHADOW", "AGENT_DRAFT", "LIVE_SEND", "COMPLETED")
ONBOARDING_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "CONFIGURATION": ("business_owner_assigned", "data_inventory_complete", "approval_matrix_approved"),
    "SHADOW": ("teams_published", "skills_published", "mailboxes_connected", "security_review_complete"),
    "AGENT_DRAFT": ("gate_b_ready", "shadow_days_complete"),
    "LIVE_SEND": ("gate_c_ready", "owner_training_complete", "support_ready"),
    "COMPLETED": ("gate_d_ready", "production_open", "handover_complete", "tenant_exit_explained"),
}

SLA_HOURS = {"P0": 1, "P1": 4, "P2": 24, "P3": 72}

GA_EVIDENCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "COMMERCIAL": ("billing_dry_run", "onboarding_rehearsal", "support_sla_drill", "legal_documents_published", "tenant_exit_drill"),
    "VALUE": ("design_partner_results", "weekly_active_rate", "artifact_adoption_rate", "time_saved", "conversion_rate", "unit_economics"),
    "GA": ("production_open_go", "penetration_test_current", "privacy_legal_approval", "thirty_day_no_p0_p1", "support_oncall_ready", "customer_exit_verified"),
}
GA_REQUIRED_ROLES: dict[str, tuple[str, ...]] = {
    "COMMERCIAL": ("product_owner", "finance_owner", "operations_owner", "privacy_owner"),
    "VALUE": ("product_owner", "business_owner", "finance_owner"),
    "GA": ("product_owner", "platform_owner", "security_owner", "privacy_owner", "operations_owner", "finance_owner"),
}
