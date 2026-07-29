"""Print code readiness and operator-owned external gates without claiming live proof."""
import json
import os
from workbuddy.settings import Settings

cfg = Settings()
production = cfg.environment.lower() in {"production", "prod"}
checks = {
    "code.model_gateway_configured": cfg.model_provider == "deterministic" or bool(cfg.model_api_key),
    "code.live_send_defaults_safe": (not cfg.enable_live_email_send) or cfg.live_send_ready,
    "code.production_auth_safe": (not production) or cfg.auth_mode in {"jwt", "oidc"},
    "code.pilot_live_send_enforcement": (not production) or cfg.require_pilot_for_live_send,
    "code.production_object_store": (not production) or cfg.object_store_provider.lower() == "s3",
    "external.gmail_oauth_configured": bool(cfg.gmail_client_id and cfg.gmail_client_secret),
    "external.graph_oauth_configured": bool(cfg.graph_client_id and cfg.graph_client_secret),
    "external.live_send_feature_flag": cfg.enable_live_email_send,
    "external.live_send_allowlist": bool(cfg.allowed_recipient_domains or cfg.allowed_recipient_addresses),
    "external.backup_target": bool(cfg.backup_bucket),
    "external.alert_target": bool(cfg.alert_webhook_url),
    "external.commercial_pricing_approved": cfg.commercial_pricing_approved,
    "external.billing_provider_configured": bool(cfg.billing_provider),
    "external.tax_region_configured": bool(cfg.tax_default_region),
    "external.stripe_configured": cfg.billing_provider != "stripe" or bool(cfg.stripe_api_key and cfg.stripe_webhook_secret),
    "external.object_store_encryption": (not production) or bool(cfg.object_store_kms_key_arn),
    "external.cloud_infra_references": (not production) or bool(cfg.gcp_project_id and cfg.entra_tenant_id),
    "external.workload_identity_pool": (not production) or bool(cfg.workload_identity_pool),
}
print(json.dumps({
    "environment": cfg.environment,
    "checks": checks,
    "note": "External configuration is preflight only. Production and Commercial GA gates require verified evidence and accountable attestations; configuration alone is insufficient.",
}, ensure_ascii=False, indent=2))
if os.getenv("WORKBUDDY_REQUIRE_EXTERNAL_GATES", "false").lower() in {"1", "true", "yes"} and not all(checks.values()):
    raise SystemExit(2)
