from __future__ import annotations

from collections.abc import Generator
from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from workbuddy.db.models import Tenant
from workbuddy.db.session import apply_tenant_context
from workbuddy.security import Principal, is_public_path, resolve_principal


def principal(request: Request) -> Principal:
    value = resolve_principal(request)
    if value is None:
        raise HTTPException(401, "authentication required")
    return value


def tenant_id(request: Request) -> str:
    return principal(request).tenant_id


def actor_id(request: Request) -> str:
    return principal(request).subject


def actor_roles(request: Request) -> tuple[str, ...]:
    return principal(request).roles


def require_actor_role(request: Request, allowed: set[str]) -> Principal:
    value = principal(request)
    if not set(value.roles).intersection(allowed):
        raise HTTPException(403, f"one of these roles is required: {', '.join(sorted(allowed))}")
    return value


def db_session(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.SessionLocal()
    try:
        if not is_public_path(request.url.path):
            value = principal(request)
            apply_tenant_context(session, value.tenant_id, local=True)
        yield session
    finally:
        session.close()


def set_tenant_context(session: Session, tenant_id: str) -> None:
    """Switch a webhook/background session into a resolved tenant context."""
    apply_tenant_context(session, tenant_id, local=True)


def require_tenant(session: Session, value: str) -> Tenant:
    tenant = session.get(Tenant, value)
    if not tenant:
        raise HTTPException(status_code=404, detail="tenant not found")
    return tenant
