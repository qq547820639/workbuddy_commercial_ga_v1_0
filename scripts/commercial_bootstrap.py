#!/usr/bin/env python3
from __future__ import annotations

import argparse
from sqlalchemy import select

from workbuddy.db.models import GAReleaseProgram, PilotProgram, TenantSubscription, CustomerOnboarding
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.services.commercial import create_ga_program, create_onboarding, create_subscription, ensure_plan_catalog
from workbuddy.services.seed import seed_all
from workbuddy.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Create honest Commercial GA starter records without faking external evidence.")
    parser.add_argument("--plan", default="starter", choices=["starter", "growth", "scale"])
    parser.add_argument("--name", default="WorkBuddy Commercial GA v1.0")
    args = parser.parse_args()
    init_db()
    with SessionLocal() as session:
        apply_tenant_context(session, settings.default_tenant_id, local=True)
        seed_all(session, settings.default_tenant_id)
        plans = ensure_plan_catalog(session, settings.default_tenant_id)
        subscription = session.scalar(select(TenantSubscription).where(TenantSubscription.tenant_id == settings.default_tenant_id, TenantSubscription.status.in_(["TRIALING", "ACTIVE"])))
        if not subscription:
            subscription = create_subscription(session, settings.default_tenant_id, "commercial-bootstrap", plan_key=args.plan, billing_cycle="monthly", trial_days=14, provider=settings.billing_provider)
        pilot = session.scalar(select(PilotProgram).where(PilotProgram.tenant_id == settings.default_tenant_id).order_by(PilotProgram.created_at.desc()))
        onboarding = session.scalar(select(CustomerOnboarding).where(CustomerOnboarding.tenant_id == settings.default_tenant_id).order_by(CustomerOnboarding.created_at.desc()))
        if not onboarding:
            onboarding = create_onboarding(session, settings.default_tenant_id, "commercial-bootstrap", name="First Design Partner", pilot_program_id=pilot.id if pilot else None)
        ga = session.scalar(select(GAReleaseProgram).where(GAReleaseProgram.tenant_id == settings.default_tenant_id).order_by(GAReleaseProgram.created_at.desc()))
        if not ga:
            ga = create_ga_program(session, settings.default_tenant_id, "commercial-bootstrap", name=args.name, pilot_program_id=pilot.id if pilot else None)
        session.commit()
        print({"plans": [x.plan_key for x in plans], "subscription": subscription.id, "subscription_status": subscription.status, "onboarding": onboarding.id, "ga_program": ga.id, "note": "No external evidence, contract, payment or legal sign-off was fabricated."})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
