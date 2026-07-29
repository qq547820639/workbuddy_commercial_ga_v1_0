#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

import jwt

from workbuddy.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a short-lived HS256 pilot JWT for staging tests.")
    parser.add_argument("--subject", default="owner")
    parser.add_argument("--tenant", default=settings.default_tenant_id)
    parser.add_argument("--roles", default="owner,product_owner,security_owner,operations_owner,privacy_owner,platform_owner,it_admin,ai_platform_owner,business_owner")
    parser.add_argument("--minutes", type=int, default=60)
    args = parser.parse_args()
    secret = settings.auth_jwt_secret or settings.app_secret
    now = datetime.now(timezone.utc)
    claims = {
        "sub": args.subject, settings.auth_tenant_claim: args.tenant,
        settings.auth_roles_claim: [x.strip() for x in args.roles.split(",") if x.strip()],
        "iat": now, "exp": now + timedelta(minutes=args.minutes),
    }
    if settings.auth_oidc_issuer:
        claims["iss"] = settings.auth_oidc_issuer
    if settings.auth_oidc_audience:
        claims["aud"] = settings.auth_oidc_audience
    print(jwt.encode(claims, secret, algorithm="HS256"))


if __name__ == "__main__":
    main()
