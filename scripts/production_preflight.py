#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import Tenant
from workbuddy.db.session import make_engine
from workbuddy.services.audit import verify_audit_chain
from workbuddy.settings import settings


def main() -> None:
    engine = make_engine()
    checks: dict[str, dict[str, object]] = {}
    production = settings.environment.lower() in {"production", "prod"}

    def check(name: str, passed: bool, detail: str) -> None:
        checks[name] = {"passed": bool(passed), "detail": detail}

    check("postgresql", (not production) or engine.dialect.name == "postgresql", f"dialect={engine.dialect.name}")
    check("https_public_url", (not production) or settings.public_base_url.startswith("https://"), settings.public_base_url)
    check("production_auth", (not production) or settings.auth_mode in {"jwt", "oidc"}, settings.auth_mode)
    check("strong_app_secret", len(settings.app_secret) >= 32 and not settings.app_secret.startswith("local-development"), "length and default-value check")
    check("token_encryption_key", bool(settings.token_encryption_key), "configured" if settings.token_encryption_key else "missing")
    check("backup_target", bool(settings.backup_bucket), settings.backup_bucket or "missing")
    check("alert_target", bool(settings.alert_webhook_url), "configured" if settings.alert_webhook_url else "missing")
    check("model_provider", settings.model_provider == "deterministic" or bool(settings.model_api_key), settings.model_provider)
    check("safe_live_send", (not settings.enable_live_email_send) or settings.live_send_ready, f"enabled={settings.enable_live_email_send}, allowlist={settings.live_send_ready}")
    check("pilot_gate_enforced_for_live_send", (not production) or settings.require_pilot_for_live_send, str(settings.require_pilot_for_live_send))
    check("production_object_store", (not production) or settings.object_store_provider.lower() == "s3", settings.object_store_provider)
    check("gmail_callback_https", (not production) or (not settings.gmail_client_id) or settings.gmail_redirect_uri.startswith("https://"), settings.gmail_redirect_uri)
    check("graph_callback_https", (not production) or (not settings.graph_client_id) or settings.graph_redirect_uri.startswith("https://"), settings.graph_redirect_uri)
    check("commercial_pricing_approved", (not production) or settings.commercial_pricing_approved, str(settings.commercial_pricing_approved))
    check("billing_provider", bool(settings.billing_provider), settings.billing_provider or "missing")
    check("tax_region_configured", bool(settings.tax_default_region), settings.tax_default_region or "missing")
    check("billing_webhook_secret", (not production) or settings.billing_provider == "manual" or bool(settings.billing_webhook_secret), "configured" if settings.billing_webhook_secret else "missing")
    check("object_store_encryption", (not production) or bool(settings.object_store_kms_key_arn), settings.object_store_kms_key_arn[:20] + "..." if settings.object_store_kms_key_arn else "missing")
    check("cloud_infra_references", (not production) or bool(settings.gcp_project_id and settings.entra_tenant_id), f"gcp={'set' if settings.gcp_project_id else 'missing'}, entra={'set' if settings.entra_tenant_id else 'missing'}")
    check("workload_identity_pool", (not production) or bool(settings.workload_identity_pool), "configured" if settings.workload_identity_pool else "missing")

    try:
        with Session(engine) as session:
            session.execute(select(1))
            tenant = session.get(Tenant, settings.default_tenant_id)
            check("database_connectivity", True, "query succeeded")
            if tenant:
                valid, broken = verify_audit_chain(session, tenant.id)
                check("audit_chain", valid, "valid" if valid else f"broken at {broken}")
            else:
                check("seed_tenant", False, "default tenant not found")
    except Exception as exc:
        check("database_connectivity", False, str(exc))

    report = {"environment": settings.environment, "ready": all(x["passed"] for x in checks.values()), "checks": checks}
    output = Path("var/production_preflight.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ready"] else 2)


if __name__ == "__main__":
    main()
