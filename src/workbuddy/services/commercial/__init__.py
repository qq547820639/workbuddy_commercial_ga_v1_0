"""Commercial domain package: billing, onboarding, operations and GA gate services.

Re-exports all public symbols previously defined in the monolithic
``workbuddy.services.commercial`` module so that
``from workbuddy.services.commercial import X`` continues to work unchanged.
"""

from __future__ import annotations

from ._common import (
    CommercialError,
    GA_EVIDENCE_REQUIREMENTS,
    GA_REQUIRED_ROLES,
    ONBOARDING_REQUIREMENTS,
    ONBOARDING_STAGES,
    REFERENCE_PLANS,
    SLA_HOURS,
)
from .billing import (
    active_subscription,
    approve_pricing,
    build_invoice,
    catalog_content_hash,
    create_subscription,
    ensure_plan_catalog,
    pricing_is_approved,
    quota_allows,
    record_usage,
    transition_invoice,
    transition_subscription,
    usage_summary,
    verify_billing_webhook,
)
from .onboarding import (
    create_onboarding,
    invite_user,
    record_value_metric,
    transition_onboarding,
    update_design_partner_profile,
    update_onboarding_checklist,
    update_user_role,
)
from .operations import (
    accept_compliance_document,
    approve_legal_document,
    check_observation_window,
    create_model_agreement,
    create_pentest_report,
    create_status_incident,
    create_support_ticket,
    legal_approval_complete,
    publish_compliance_document,
    start_observation_window,
    update_status_incident,
    update_support_ticket,
)
from .ga import (
    attest_ga_gate,
    create_ga_program,
    evaluate_ga_gate,
    ga_evidence_snapshot_hash,
    ga_go_no_go_report,
    submit_ga_evidence,
    verify_ga_evidence,
)

__all__ = [
    # _common
    "CommercialError",
    "REFERENCE_PLANS",
    "ONBOARDING_STAGES",
    "ONBOARDING_REQUIREMENTS",
    "SLA_HOURS",
    "GA_EVIDENCE_REQUIREMENTS",
    "GA_REQUIRED_ROLES",
    # billing
    "ensure_plan_catalog",
    "active_subscription",
    "create_subscription",
    "transition_subscription",
    "record_usage",
    "usage_summary",
    "quota_allows",
    "build_invoice",
    "transition_invoice",
    "verify_billing_webhook",
    "catalog_content_hash",
    "approve_pricing",
    "pricing_is_approved",
    # onboarding
    "create_onboarding",
    "update_onboarding_checklist",
    "transition_onboarding",
    "update_design_partner_profile",
    "record_value_metric",
    "invite_user",
    "update_user_role",
    # operations
    "create_support_ticket",
    "update_support_ticket",
    "create_status_incident",
    "update_status_incident",
    "publish_compliance_document",
    "accept_compliance_document",
    "approve_legal_document",
    "legal_approval_complete",
    "create_model_agreement",
    "create_pentest_report",
    "start_observation_window",
    "check_observation_window",
    # ga
    "create_ga_program",
    "submit_ga_evidence",
    "verify_ga_evidence",
    "ga_evidence_snapshot_hash",
    "attest_ga_gate",
    "evaluate_ga_gate",
    "ga_go_no_go_report",
]
