#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from sqlalchemy.orm import Session

from workbuddy.db.session import apply_tenant_context, make_engine
from workbuddy.services.pilot import create_program, transition_program
from workbuddy.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and optionally activate a production pilot program.")
    parser.add_argument("--name", default=settings.pilot_name)
    parser.add_argument("--actor", default="product-owner")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    engine = make_engine()
    with Session(engine) as session:
        apply_tenant_context(session, settings.default_tenant_id)
        program = create_program(
            session, settings.default_tenant_id, args.actor, name=args.name,
            scope={"teams": ["sales-growth", "operations-delivery", "customer-success"], "max_users": 20},
            owners={"security_owner_id": "security-owner", "operations_owner_id": "operations-owner", "privacy_owner_id": "privacy-owner"},
        )
        if args.activate and program.status == "DRAFT":
            transition_program(session, settings.default_tenant_id, program.id, args.actor, "ACTIVE")
        session.commit()
        print(json.dumps({"id": program.id, "name": program.name, "status": program.status}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
