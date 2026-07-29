#!/usr/bin/env python3
from __future__ import annotations

import argparse
from uuid import uuid4
from sqlalchemy import select

from workbuddy.db.models import Tenant, User
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.services.seed import seed_all


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision an isolated WorkBuddy tenant. Run with database administrator credentials.")
    parser.add_argument("--tenant-id", default=None)
    parser.add_argument("--name", required=True)
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--owner-name", default="Owner")
    args = parser.parse_args()
    init_db(); tenant_id = args.tenant_id or str(uuid4())
    with SessionLocal() as session:
        if session.get(Tenant, tenant_id):
            raise SystemExit("tenant id already exists")
        session.add(Tenant(id=tenant_id, name=args.name, status="provisioning")); session.flush()
        apply_tenant_context(session, tenant_id, local=True)
        seed_all(session, tenant_id)
        owner = session.scalar(select(User).where(User.tenant_id == tenant_id, User.email == "owner@workbuddy.local"))
        if owner:
            owner.email = args.owner_email.lower(); owner.name = args.owner_name; owner.role = "owner"
        session.get(Tenant, tenant_id).status = "active"
        session.commit()
        print({"tenant_id": tenant_id, "name": args.name, "owner_email": args.owner_email, "status": "active"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
