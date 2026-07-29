from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _csv(name: str) -> tuple[str, ...]:
    return tuple(x.strip().lower() for x in os.getenv(name, "").split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("WORKBUDDY_ENVIRONMENT", "local")
    database_url: str = os.getenv("WORKBUDDY_DATABASE_URL", "sqlite:///./workbuddy.db")
    app_secret: str = os.getenv("WORKBUDDY_APP_SECRET", "local-development-secret-change-me-123456")
    token_encryption_key: str = os.getenv("WORKBUDDY_TOKEN_ENCRYPTION_KEY", "")
    default_tenant_id: str = os.getenv("WORKBUDDY_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-000000000001")
    public_base_url: str = os.getenv("WORKBUDDY_PUBLIC_BASE_URL", "http://localhost:8000")
    object_store_dir: str = os.getenv("WORKBUDDY_OBJECT_STORE_DIR", "./var/objects")
    object_store_provider: str = os.getenv("WORKBUDDY_OBJECT_STORE_PROVIDER", "filesystem")
    object_store_bucket: str = os.getenv("WORKBUDDY_OBJECT_STORE_BUCKET", "")
    object_store_region: str = os.getenv("WORKBUDDY_OBJECT_STORE_REGION", "")
    object_store_endpoint: str = os.getenv("WORKBUDDY_OBJECT_STORE_ENDPOINT", "")

    # Authentication. local_headers is for local development only. Production pilot
    # must use JWT/OIDC claims for tenant and actor identity.
    auth_mode: str = os.getenv("WORKBUDDY_AUTH_MODE", "local_headers")
    auth_jwt_secret: str = os.getenv("WORKBUDDY_AUTH_JWT_SECRET", "")
    auth_jwt_algorithm: str = os.getenv("WORKBUDDY_AUTH_JWT_ALGORITHM", "HS256")
    auth_oidc_issuer: str = os.getenv("WORKBUDDY_AUTH_OIDC_ISSUER", "")
    auth_oidc_audience: str = os.getenv("WORKBUDDY_AUTH_OIDC_AUDIENCE", "")
    auth_jwks_url: str = os.getenv("WORKBUDDY_AUTH_JWKS_URL", "")
    auth_tenant_claim: str = os.getenv("WORKBUDDY_AUTH_TENANT_CLAIM", "tenant_id")
    auth_roles_claim: str = os.getenv("WORKBUDDY_AUTH_ROLES_CLAIM", "roles")

    # Production pilot operations.
    backup_bucket: str = os.getenv("WORKBUDDY_BACKUP_BUCKET", "")
    alert_webhook_url: str = os.getenv("WORKBUDDY_ALERT_WEBHOOK_URL", "")
    pilot_name: str = os.getenv("WORKBUDDY_PILOT_NAME", "WorkBuddy Production Pilot")

    # Commercial controls. Reference prices are not chargeable until an accountable
    # owner explicitly approves the catalog and a real billing/contract reference exists.
    commercial_pricing_approved: bool = _bool("WORKBUDDY_COMMERCIAL_PRICING_APPROVED", False)
    billing_provider: str = os.getenv("WORKBUDDY_BILLING_PROVIDER", "manual")
    billing_webhook_secret: str = os.getenv("WORKBUDDY_BILLING_WEBHOOK_SECRET", "")
    tax_default_region: str = os.getenv("WORKBUDDY_TAX_DEFAULT_REGION", "CN")
    stripe_api_key: str = os.getenv("WORKBUDDY_STRIPE_API_KEY", "")
    stripe_webhook_secret: str = os.getenv("WORKBUDDY_STRIPE_WEBHOOK_SECRET", "")
    stripe_api_base_url: str = os.getenv("WORKBUDDY_STRIPE_API_BASE_URL", "https://api.stripe.com/v1")

    # Object store encryption (Gap 4).
    object_store_kms_key_arn: str = os.getenv("WORKBUDDY_OBJECT_STORE_KMS_KEY_ARN", "")
    db_encryption_key_ref: str = os.getenv("WORKBUDDY_DB_ENCRYPTION_KEY_REF", "")

    # Cloud infrastructure references (Gap 3).
    gcp_project_id: str = os.getenv("WORKBUDDY_GCP_PROJECT_ID", "")
    gcp_region: str = os.getenv("WORKBUDDY_GCP_REGION", "asia-east2")
    entra_tenant_id: str = os.getenv("WORKBUDDY_ENTRA_TENANT_ID", "")
    workload_identity_pool: str = os.getenv("WORKBUDDY_WORKLOAD_IDENTITY_POOL", "")

    # Model Gateway. Without an API key the controlled Beta uses the deterministic provider.
    model_provider: str = os.getenv("WORKBUDDY_MODEL_PROVIDER", "deterministic")
    model_name: str = os.getenv("WORKBUDDY_MODEL_NAME", "gpt-5-mini")
    model_base_url: str = os.getenv("WORKBUDDY_MODEL_BASE_URL", "https://api.openai.com/v1")
    model_api_key: str = os.getenv("WORKBUDDY_MODEL_API_KEY", "")
    model_timeout_seconds: int = _int("WORKBUDDY_MODEL_TIMEOUT_SECONDS", 60)
    model_max_output_tokens: int = _int("WORKBUDDY_MODEL_MAX_OUTPUT_TOKENS", 4000)
    model_daily_budget_cny_fen: int = _int("WORKBUDDY_MODEL_DAILY_BUDGET_CNY_FEN", 10000)
    model_input_cost_cny_fen_per_million: int = _int("WORKBUDDY_MODEL_INPUT_COST_CNY_FEN_PER_MILLION", 0)
    model_output_cost_cny_fen_per_million: int = _int("WORKBUDDY_MODEL_OUTPUT_COST_CNY_FEN_PER_MILLION", 0)

    gmail_client_id: str = os.getenv("WORKBUDDY_GMAIL_CLIENT_ID", "")
    gmail_client_secret: str = os.getenv("WORKBUDDY_GMAIL_CLIENT_SECRET", "")
    gmail_redirect_uri: str = os.getenv("WORKBUDDY_GMAIL_REDIRECT_URI", "http://localhost:8000/v1/connectors/gmail/callback")
    gmail_topic_name: str = os.getenv("WORKBUDDY_GMAIL_TOPIC_NAME", "")
    gmail_pubsub_verification_token: str = os.getenv("WORKBUDDY_GMAIL_PUBSUB_VERIFICATION_TOKEN", "")

    graph_client_id: str = os.getenv("WORKBUDDY_GRAPH_CLIENT_ID", "")
    graph_client_secret: str = os.getenv("WORKBUDDY_GRAPH_CLIENT_SECRET", "")
    graph_tenant: str = os.getenv("WORKBUDDY_GRAPH_TENANT", "common")
    graph_redirect_uri: str = os.getenv("WORKBUDDY_GRAPH_REDIRECT_URI", "http://localhost:8000/v1/connectors/graph/callback")
    graph_webhook_client_state: str = os.getenv("WORKBUDDY_GRAPH_WEBHOOK_CLIENT_STATE", "")
    graph_subscription_hours: int = _int("WORKBUDDY_GRAPH_SUBSCRIPTION_HOURS", 70)

    # External-action safety. Live sending is off until explicitly enabled.
    enable_live_email_send: bool = _bool("WORKBUDDY_ENABLE_LIVE_EMAIL_SEND", False)
    require_pilot_for_live_send: bool = _bool("WORKBUDDY_REQUIRE_PILOT_FOR_LIVE_SEND", False)
    allowed_recipient_domains: tuple[str, ...] = _csv("WORKBUDDY_ALLOWED_RECIPIENT_DOMAINS")
    allowed_recipient_addresses: tuple[str, ...] = _csv("WORKBUDDY_ALLOWED_RECIPIENT_ADDRESSES")
    daily_send_limit: int = _int("WORKBUDDY_DAILY_SEND_LIMIT", 20)
    mission_send_limit: int = _int("WORKBUDDY_MISSION_SEND_LIMIT", 3)
    allow_bcc: bool = _bool("WORKBUDDY_ALLOW_BCC", False)
    allow_attachments: bool = _bool("WORKBUDDY_ALLOW_ATTACHMENTS", False)

    # Pilot behavior.
    dispatch_shadow_mode: bool = _bool("WORKBUDDY_DISPATCH_SHADOW_MODE", True)
    dispatch_auto_route_min_confidence: int = _int("WORKBUDDY_DISPATCH_AUTO_ROUTE_MIN_CONFIDENCE", 95)
    worker_poll_seconds: int = _int("WORKBUDDY_WORKER_POLL_SECONDS", 5)

    @property
    def fernet_key(self) -> bytes:
        if self.token_encryption_key:
            return self.token_encryption_key.encode()
        digest = hashlib.sha256(self.app_secret.encode()).digest()
        return base64.urlsafe_b64encode(digest)

    @property
    def live_send_ready(self) -> bool:
        return self.enable_live_email_send and bool(self.allowed_recipient_domains or self.allowed_recipient_addresses)


settings = Settings()
