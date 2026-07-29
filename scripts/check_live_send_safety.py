#!/usr/bin/env python3
"""Gap 6: Pre-send safety verification.

Reads the operational safety settings and prints a JSON report with a pass/fail
verdict for each control that must hold before a live external email send is
allowed: recipient allowlist, daily send limit, mission send limit, BCC and
attachment policy, and pilot-gate enforcement. This is a preflight check only;
it does not send any email and does not fabricate evidence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbuddy.settings import settings


def main() -> None:
    tenant_id = settings.default_tenant_id
    production = settings.environment.lower() in {"production", "prod"}

    checks: dict[str, dict[str, object]] = {}

    # Recipient allowlist: live sending must be constrained to a known set of
    # domains or explicit addresses so an agent cannot email arbitrary recipients.
    has_allowlist = bool(
        settings.allowed_recipient_domains or settings.allowed_recipient_addresses
    )
    checks["recipient_allowlist"] = {
        "passed": has_allowlist,
        "allowed_domains": list(settings.allowed_recipient_domains),
        "allowed_addresses": list(settings.allowed_recipient_addresses),
    }

    # Daily send limit: must be a positive integer so a runaway agent is bounded.
    checks["daily_send_limit"] = {
        "passed": settings.daily_send_limit > 0,
        "limit": settings.daily_send_limit,
    }

    # Mission send limit: bounds how many external sends a single mission can do.
    checks["mission_send_limit"] = {
        "passed": settings.mission_send_limit > 0,
        "limit": settings.mission_send_limit,
    }

    # BCC policy: blind-copy recipients are hidden from the owner audit trail, so
    # BCC must be disabled for safe operation.
    checks["bcc_policy"] = {
        "passed": not settings.allow_bcc,
        "allow_bcc": settings.allow_bcc,
    }

    # Attachment policy: attachments expand the data-leak surface, so they must
    # be disabled unless explicitly approved.
    checks["attachment_policy"] = {
        "passed": not settings.allow_attachments,
        "allow_attachments": settings.allow_attachments,
    }

    # Pilot gate enforcement: in production, live sending must require an active
    # production pilot so an unsupervised tenant cannot send immediately.
    pilot_gate_required = production or settings.require_pilot_for_live_send
    checks["pilot_gate_enforcement"] = {
        "passed": settings.require_pilot_for_live_send if production else True,
        "require_pilot_for_live_send": settings.require_pilot_for_live_send,
        "enforced_in_production": settings.require_pilot_for_live_send if production else None,
    }

    # Overall live-send readiness derived from the configured feature flag and
    # the allowlist presence (mirrors Settings.live_send_ready).
    checks["live_send_ready"] = {
        "passed": settings.live_send_ready,
        "enable_live_email_send": settings.enable_live_email_send,
        "has_allowlist": has_allowlist,
    }

    report = {
        "gap": 6,
        "title": "Pre-send safety verification",
        "tenant_id": tenant_id,
        "environment": settings.environment,
        "production": production,
        "ready": all(check["passed"] for check in checks.values()),
        "checks": checks,
        "note": (
            "Live sending stays disabled until an owner explicitly enables it and "
            "configures an allowlist. This check does not send email or fabricate evidence."
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["ready"] else 2)


if __name__ == "__main__":
    main()
