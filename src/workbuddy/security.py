from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request
from jwt import PyJWKClient

from workbuddy.settings import settings


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    roles: tuple[str, ...]
    claims: dict[str, Any]


PUBLIC_PATHS = {
    "/", "/health", "/health/live", "/health/ready", "/auth/config",
    "/v1/connectors/gmail/callback", "/v1/connectors/gmail/webhook",
    "/v1/connectors/graph/callback", "/v1/connectors/graph/webhook",
}


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith("/docs") or path.startswith("/openapi")


def _roles(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(x.strip() for x in value.replace(",", " ").split() if x.strip())
    if isinstance(value, list):
        return tuple(str(x) for x in value)
    return ()


def _decode_bearer(token: str) -> dict[str, Any]:
    options = {"require": ["sub", settings.auth_tenant_claim]}
    kwargs: dict[str, Any] = {"algorithms": [settings.auth_jwt_algorithm], "options": options}
    if settings.auth_oidc_audience:
        kwargs["audience"] = settings.auth_oidc_audience
    else:
        kwargs["options"] = {**options, "verify_aud": False}
    if settings.auth_oidc_issuer:
        kwargs["issuer"] = settings.auth_oidc_issuer
    if settings.auth_jwks_url:
        key = PyJWKClient(settings.auth_jwks_url).get_signing_key_from_jwt(token).key
    elif settings.auth_jwt_secret:
        key = settings.auth_jwt_secret
    else:
        raise HTTPException(503, "JWT authentication is configured without a verification key")
    try:
        return jwt.decode(token, key=key, **kwargs)
    except jwt.PyJWTError as exc:
        raise HTTPException(401, f"invalid bearer token: {exc}") from exc


def resolve_principal(request: Request, *, allow_public: bool = False) -> Principal | None:
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    if allow_public and is_public_path(request.url.path):
        return None
    if settings.auth_mode == "local_headers":
        if settings.environment.lower() in {"production", "prod"}:
            raise HTTPException(503, "local header authentication is forbidden in production")
        principal = Principal(
            subject=request.headers.get("X-Actor-ID") or "owner",
            tenant_id=request.headers.get("X-Tenant-ID") or settings.default_tenant_id,
            roles=_roles(request.headers.get("X-Roles") or "owner product_owner security_owner operations_owner privacy_owner platform_owner it_admin ai_platform_owner business_owner finance_owner legal_owner support_owner"),
            claims={"mode": "local_headers"},
        )
    elif settings.auth_mode in {"jwt", "oidc"}:
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        claims = _decode_bearer(authorization[7:].strip())
        tenant = claims.get(settings.auth_tenant_claim)
        if not tenant:
            raise HTTPException(401, "tenant claim missing")
        principal = Principal(
            subject=str(claims["sub"]), tenant_id=str(tenant),
            roles=_roles(claims.get(settings.auth_roles_claim)), claims=claims,
        )
    else:
        raise HTTPException(503, "unsupported authentication mode")
    request.state.principal = principal
    return principal
