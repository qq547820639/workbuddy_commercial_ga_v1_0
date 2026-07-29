#!/usr/bin/env python3
"""Gap 11: Observation window checker.

Gets the active (OBSERVING) observation window for a GA program and calls
``check_observation_window()`` to detect P0/P1 incidents and reset or complete
the window as needed. If no active window exists but a GA program is present, a
30-day window is started first so the check has something to evaluate. Prints a
JSON report of the window status before and after the check.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbuddy.db.models import GAReleaseProgram, ObservationWindow
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.services.commercial import (
    check_observation_window,
    start_observation_window,
)
from workbuddy.settings import settings


def _serialize_window(window: ObservationWindow | None) -> dict | None:
    if window is None:
        return None
    return {
        "id": window.id,
        "ga_program_id": window.ga_program_id,
        "status": window.status,
        "window_start": window.window_start.isoformat(),
        "window_end": window.window_end.isoformat(),
        "p0_p1_count": window.p0_p1_count,
        "reset_count": window.reset_count,
        "reset_reason": window.reset_reason,
        "completed_at": window.completed_at.isoformat() if window.completed_at else None,
        "content_hash": window.content_hash,
    }


def _resolve_program(session: Session, tenant_id: str, program_id: str | None) -> GAReleaseProgram | None:
    if program_id:
        return session.get(GAReleaseProgram, program_id)
    return session.scalar(
        select(GAReleaseProgram)
        .where(GAReleaseProgram.tenant_id == tenant_id)
        .order_by(GAReleaseProgram.created_at.desc())
    )


def _active_window(session: Session, tenant_id: str, program_id: str) -> ObservationWindow | None:
    return session.scalar(
        select(ObservationWindow).where(
            ObservationWindow.tenant_id == tenant_id,
            ObservationWindow.ga_program_id == program_id,
            ObservationWindow.status == "OBSERVING",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the GA observation window for P0/P1 incidents.")
    parser.add_argument("program_id", nargs="?", help="GA release program id (defaults to the latest program).")
    parser.add_argument("--days", type=int, default=30, help="Observation window length in days when starting a new one.")
    args = parser.parse_args()

    init_db()
    tenant_id = settings.default_tenant_id
    actor_id = "observation-checker"

    with SessionLocal() as session:
        apply_tenant_context(session, tenant_id, local=True)

        program = _resolve_program(session, tenant_id, args.program_id)
        report: dict = {
            "gap": 11,
            "title": "Observation window checker",
            "tenant_id": tenant_id,
        }
        if not program:
            report["program"] = None
            report["window_before"] = None
            report["window_after"] = None
            report["note"] = "No GA release program found. Nothing to observe."
            report["ok"] = False
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return

        report["program"] = {"id": program.id, "name": program.name, "status": program.status}

        window = _active_window(session, tenant_id, program.id)
        started_now = False
        if not window:
            # No active window to check. Start a 30-day window so the check has
            # something to evaluate and the lifecycle is demonstrated.
            window = start_observation_window(
                session, tenant_id, actor_id, program.id, days=args.days,
            )
            started_now = True
        report["started_window"] = started_now
        report["window_before"] = _serialize_window(window)

        # Run the check: detect P0/P1 incidents (reset if found) or complete the
        # window if the incident-free period has elapsed.
        checked = check_observation_window(session, tenant_id, program.id)
        report["window_after"] = _serialize_window(checked)

        session.commit()

    before = report["window_before"] or {}
    after = report["window_after"] or {}
    report["transition"] = {
        "status_before": before.get("status"),
        "status_after": after.get("status"),
        "reset_count_before": before.get("reset_count"),
        "reset_count_after": after.get("reset_count"),
        "p0_p1_count_before": before.get("p0_p1_count"),
        "p0_p1_count_after": after.get("p0_p1_count"),
    }
    report["ok"] = after.get("status") in {"OBSERVING", "COMPLETED"}
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
