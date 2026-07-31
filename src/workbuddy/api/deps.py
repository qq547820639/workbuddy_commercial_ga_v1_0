from __future__ import annotations

from collections.abc import Generator
from fastapi import Depends, HTTPException, Request
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
    """Request-scoped DB session acting as the unit of work.

    Commits on success, rolls back on exception, and always closes the session.
    Route handlers should NOT call ``session.commit()`` explicitly — it is handled
    here automatically after the route returns.
    """
    session = request.app.state.SessionLocal()
    try:
        if not is_public_path(request.url.path):
            value = principal(request)
            apply_tenant_context(session, value.tenant_id, local=True)
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
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


class TenantContext:
    """Bundled tenant-scoped request context for route handlers.

    Replaces the repeated
    ``tid=Depends(tenant_id), session=Depends(db_session)[, actor=Depends(actor_id)]``
    + ``require_tenant(session, tid)`` boilerplate found across routes. The tenant
    existence check is performed once, inside the dependency.
    """

    def __init__(
        self,
        tenant_id: str = Depends(tenant_id),
        session: Session = Depends(db_session),
        actor: str = Depends(actor_id),
    ) -> None:
        self.tenant_id = tenant_id
        self.session = session
        self.actor = actor
        self.tenant = require_tenant(session, tenant_id)
