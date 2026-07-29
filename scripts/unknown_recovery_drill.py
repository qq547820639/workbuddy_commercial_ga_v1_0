#!/usr/bin/env python3
"""Gap 6: Unknown-result recovery drill.

A live external send can end in an UNKNOWN state when the provider accepts the
request but the result cannot be confirmed (network interruption, 5xx, provider
record unverifiable). Direct retries are prohibited because they risk a
duplicate send. This drill creates test ExternalOperation rows already in the
UNKNOWN state and walks the recovery flow for both outcomes:

  resolve  -> verify_unknown_external_operation(outcome="succeeded")
              UNKNOWN -> VERIFYING (review/classify) -> SUCCEEDED
  revoke   -> verify_unknown_external_operation(outcome="failed")
              UNKNOWN -> VERIFYING (review/classify) -> FAILED

No real email is sent; demo_mode is always True for the seeded operations.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbuddy.db.models import ExternalOperation, Mission, Tenant
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.domain.state_machine import ExternalOperationStatus, MissionStatus
from workbuddy.services.common import content_hash, utcnow
from workbuddy.services.external_actions import verify_unknown_external_operation
from workbuddy.settings import settings


def _ensure_tenant(session: Session, tenant_id: str) -> None:
    if not session.get(Tenant, tenant_id):
        session.add(Tenant(id=tenant_id, name="WorkBuddy Demo Company"))
        session.flush()


def _seed_unknown_operation(session: Session, tenant_id: str, label: str) -> tuple[Mission, ExternalOperation]:
    """Create a mission and an ExternalOperation already stuck in UNKNOWN."""
    suffix = uuid.uuid4().hex[:8]
    mission = Mission(
        tenant_id=tenant_id,
        source_type="drill",
        source_id=f"unknown-recovery-{suffix}",
        title=f"Unknown recovery drill ({label})",
        objective="Simulate a send whose provider result could not be confirmed.",
        risk_level="medium",
        status=MissionStatus.UNKNOWN.value,
    )
    session.add(mission)
    session.flush()

    parameters = {
        "account_id": None,
        "to": ["allowlisted@example.com"],
        "subject": f"Unknown recovery drill ({label})",
        "body": "drill payload - no real email",
    }
    op = ExternalOperation(
        tenant_id=tenant_id,
        mission_id=mission.id,
        operation_key=f"unknown-recovery-drill-{label}-{suffix}",
        operation_type="email_send",
        status=ExternalOperationStatus.UNKNOWN.value,
        parameters=parameters,
        parameters_hash=content_hash(parameters),
        demo_mode=True,
        error_code="SIMULATED_UNKNOWN",
        executed_at=utcnow(),
    )
    session.add(op)
    session.flush()
    return mission, op


def _run_drill(session: Session, tenant_id: str, label: str, outcome: str) -> dict:
    mission, op = _seed_unknown_operation(session, tenant_id, label)
    before = {
        "operation_id": op.id,
        "operation_key": op.operation_key,
        "operation_status_before": op.status,
        "mission_status_before": mission.status,
        "error_code": op.error_code,
    }
    try:
        recovered = verify_unknown_external_operation(
            session, tenant_id, op.id, outcome,
        )
        session.refresh(mission)
        after = {
            "operation_status_after": recovered.status,
            "mission_status_after": mission.status,
            "verified_at": recovered.verified_at.isoformat() if recovered.verified_at else None,
            "provider_result": recovered.provider_result,
        }
        return {
            "label": label,
            "outcome": outcome,
            "before": before,
            "after": after,
            "ok": True,
            "error": None,
        }
    except Exception as exc:
        return {
            "label": label,
            "outcome": outcome,
            "before": before,
            "after": None,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> None:
    init_db()
    tenant_id = settings.default_tenant_id
    report: dict = {
        "gap": 6,
        "title": "Unknown-result recovery drill",
        "tenant_id": tenant_id,
        "note": "Demo-mode operations only. No real email is sent.",
        "drills": [],
    }

    with SessionLocal() as session:
        apply_tenant_context(session, tenant_id, local=True)
        _ensure_tenant(session, tenant_id)

        # Drill 1: review/classify -> resolve (UNKNOWN -> VERIFYING -> SUCCEEDED)
        report["drills"].append(
            _run_drill(session, tenant_id, "resolve", "succeeded")
        )
        # Drill 2: review/classify -> revoke (UNKNOWN -> VERIFYING -> FAILED)
        report["drills"].append(
            _run_drill(session, tenant_id, "revoke", "failed")
        )

        session.commit()

    report["ok"] = all(d["ok"] for d in report["drills"])
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
