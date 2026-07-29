from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

import workbuddy.security as security
from workbuddy.api.main import create_app
from workbuddy.settings import settings as base_settings

TENANT = "00000000-0000-0000-0000-000000000001"


def test_jwt_claims_replace_spoofable_tenant_headers(tmp_path, monkeypatch):
    configured = replace(
        base_settings,
        auth_mode="jwt",
        auth_jwt_secret="pilot-jwt-secret-with-at-least-32-chars",
        auth_jwt_algorithm="HS256",
        auth_oidc_audience="workbuddy-api",
        auth_oidc_issuer="https://identity.example/",
    )
    monkeypatch.setattr(security, "settings", configured)
    app = create_app(f"sqlite:///{tmp_path / 'auth.db'}", auto_seed=True)
    now = datetime.now(timezone.utc)
    token = jwt.encode({
        "sub": "pilot-owner", "tenant_id": TENANT,
        "roles": ["owner", "product_owner"], "aud": "workbuddy-api",
        "iss": "https://identity.example/", "iat": now, "exp": now + timedelta(minutes=5),
    }, configured.auth_jwt_secret, algorithm="HS256")
    with TestClient(app) as client:
        missing = client.get("/v1/dashboard")
        assert missing.status_code == 401
        response = client.get("/v1/dashboard", headers={
            "Authorization": f"Bearer {token}",
            "X-Tenant-ID": "00000000-0000-0000-0000-000000000999",
            "X-Actor-ID": "spoofed",
        })
        assert response.status_code == 200
