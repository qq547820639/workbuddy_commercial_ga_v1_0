#!/usr/bin/env python3
"""Gap 9: On-call drill.

Creates a test on-call schedule with primary and secondary shifts, verifies that
``current_responder`` returns the active shift, configures an escalation policy
for P0/P1, and checks that primary coverage is complete for the next 7 days.
Prints a JSON report of the drill. Each run uses a uniquely-named schedule so
the drill is repeatable without colliding with prior runs.
"""
from __future__ import annotations

import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbuddy.db.models import Tenant
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.services.common import utcnow
from workbuddy.services.oncall import (
    create_schedule,
    create_shift,
    current_responder,
    oncall_coverage_complete,
    set_escalation_policy,
)
from workbuddy.settings import settings


def _ensure_tenant(session: Session, tenant_id: str) -> None:
    if not session.get(Tenant, tenant_id):
        session.add(Tenant(id=tenant_id, name="WorkBuddy Demo Company"))
        session.flush()


def _shift_summary(shift) -> dict:
    return {
        "id": shift.id,
        "responder_id": shift.responder_id,
        "responder_contact": shift.responder_contact,
        "role": shift.role,
        "shift_start": shift.shift_start.isoformat(),
        "shift_end": shift.shift_end.isoformat(),
    }


def main() -> None:
    init_db()
    tenant_id = settings.default_tenant_id
    actor_id = "oncall-drill"
    now = utcnow()
    report: dict = {
        "gap": 9,
        "title": "On-call drill",
        "tenant_id": tenant_id,
        "run_at": now.isoformat(),
        "steps": [],
    }

    with SessionLocal() as session:
        apply_tenant_context(session, tenant_id, local=True)
        _ensure_tenant(session, tenant_id)

        # Step 1: create a uniquely-named schedule for this drill run.
        schedule = create_schedule(
            session, tenant_id, actor_id,
            name=f"On-Call Drill {uuid.uuid4().hex[:8]}",
            timezone="Asia/Shanghai",
        )
        report["schedule"] = {
            "id": schedule.id,
            "name": schedule.name,
            "timezone": schedule.timezone,
        }
        report["steps"].append({"step": "create_schedule", "id": schedule.id})

        # Step 2: create a primary shift covering the current moment, plus a
        # secondary backup shift overlapping the same window.
        primary = create_shift(
            session, tenant_id, actor_id,
            schedule_id=schedule.id,
            responder_id="responder-primary",
            responder_contact="pagerduty://primary-oncall",
            role="primary",
            shift_start=now - timedelta(hours=1),
            shift_end=now + timedelta(hours=7),
        )
        secondary = create_shift(
            session, tenant_id, actor_id,
            schedule_id=schedule.id,
            responder_id="responder-secondary",
            responder_contact="pagerduty://secondary-oncall",
            role="secondary",
            shift_start=now - timedelta(hours=1),
            shift_end=now + timedelta(hours=7),
        )
        report["shifts"] = [_shift_summary(primary), _shift_summary(secondary)]
        report["steps"].append(
            {"step": "create_shifts", "count": 2}
        )

        # Step 3: verify current_responder returns the active primary first.
        responders = current_responder(session, tenant_id, schedule_id=schedule.id)
        report["current_responder"] = [
            {
                "responder_id": r.responder_id,
                "role": r.role,
                "shift_start": r.shift_start.isoformat(),
                "shift_end": r.shift_end.isoformat(),
            }
            for r in responders
        ]
        primary_is_current = bool(responders) and responders[0].role == "primary"
        report["steps"].append(
            {"step": "current_responder", "primary_is_current": primary_is_current}
        )

        # Step 4: configure escalation policies for P0 and P1.
        p0_policy = set_escalation_policy(
            session, tenant_id, actor_id,
            severity="P0",
            steps=[
                {"wait_minutes": 0, "notify": "primary-oncall"},
                {"wait_minutes": 5, "notify": "secondary-oncall"},
                {"wait_minutes": 15, "notify": "engineering-manager"},
                {"wait_minutes": 30, "notify": "incident-commander"},
            ],
        )
        p1_policy = set_escalation_policy(
            session, tenant_id, actor_id,
            severity="P1",
            steps=[
                {"wait_minutes": 0, "notify": "primary-oncall"},
                {"wait_minutes": 15, "notify": "secondary-oncall"},
                {"wait_minutes": 60, "notify": "engineering-manager"},
            ],
        )
        report["escalation_policies"] = {
            "P0": {"severity": p0_policy.severity, "steps": p0_policy.steps},
            "P1": {"severity": p1_policy.severity, "steps": p1_policy.steps},
        }
        report["steps"].append(
            {"step": "set_escalation_policy", "configured": ["P0", "P1"]}
        )

        # Step 5: check 7-day primary coverage. The primary shift above only
        # covers ~7 hours, so coverage is expected to be incomplete — the drill
        # reports the honest result rather than faking a 7-day rotation.
        coverage_complete = oncall_coverage_complete(session, tenant_id, days=7)
        report["coverage"] = {
            "days_checked": 7,
            "complete": coverage_complete,
            "note": (
                "A single drill shift cannot cover 7 days; a real rota needs "
                "continuous primary shifts. This reports the true coverage state."
            ),
        }
        report["steps"].append(
            {"step": "oncall_coverage_complete", "complete": coverage_complete}
        )

        session.commit()

    report["ok"] = primary_is_current
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
