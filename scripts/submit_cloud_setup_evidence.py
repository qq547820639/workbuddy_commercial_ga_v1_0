#!/usr/bin/env python3
"""Gap 3: Submit cloud setup evidence.

Verifies the cloud infrastructure references required for production
(GCP project, region, Microsoft Entra tenant, and workload identity pool) and,
when all are configured, submits the corresponding GA evidence under the
``production_open_go`` evidence type. When references are missing, the gap is
reported honestly and no evidence is submitted, so the infrastructure gap stays
visible rather than being papered over.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbuddy.db.models import GAReleaseProgram
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.services.commercial import submit_ga_evidence
from workbuddy.settings import settings


def _resolve_program(session: Session, tenant_id: str, program_id: str | None) -> GAReleaseProgram | None:
    if program_id:
        return session.get(GAReleaseProgram, program_id)
    return session.scalar(
        select(GAReleaseProgram)
        .where(GAReleaseProgram.tenant_id == tenant_id)
        .order_by(GAReleaseProgram.created_at.desc())
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify cloud setup references and submit GA evidence.")
    parser.add_argument("program_id", nargs="?", help="GA release program id (defaults to the latest program).")
    args = parser.parse_args()

    init_db()
    tenant_id = settings.default_tenant_id
    actor_id = "cloud-setup-submitter"

    # Verify cloud infrastructure references from settings.
    refs = {
        "gcp_project_id": settings.gcp_project_id,
        "gcp_region": settings.gcp_region,
        "entra_tenant_id": settings.entra_tenant_id,
        "workload_identity_pool": settings.workload_identity_pool,
    }
    verification = {
        key: {"configured": bool(value), "value": value or None}
        for key, value in refs.items()
    }
    all_configured = all(item["configured"] for item in verification.values())

    report: dict = {
        "gap": 3,
        "title": "Submit cloud setup evidence",
        "tenant_id": tenant_id,
        "verification": verification,
        "all_references_configured": all_configured,
    }

    with SessionLocal() as session:
        apply_tenant_context(session, tenant_id, local=True)
        program = _resolve_program(session, tenant_id, args.program_id)
        report["program"] = {"id": program.id, "name": program.name} if program else None

        if not all_configured:
            # Do not fabricate evidence for unconfigured infrastructure.
            missing = [k for k, v in verification.items() if not v["configured"]]
            report["submitted"] = False
            report["ga_evidence"] = None
            report["error"] = (
                "Cloud infrastructure references are not fully configured "
                f"(missing: {', '.join(missing)}). Evidence was not submitted."
            )
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return

        if not program:
            report["submitted"] = False
            report["ga_evidence"] = None
            report["error"] = "All cloud references are configured, but no GA release program exists to attach evidence to."
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return

        # All references configured and a program exists: submit the evidence.
        try:
            evidence = submit_ga_evidence(
                session, tenant_id, program.id, actor_id,
                gate_key="GA",
                evidence_type="production_open_go",
                source="cloud-setup-verification",
                metrics={
                    "gcp_project_id": settings.gcp_project_id,
                    "gcp_region": settings.gcp_region,
                    "entra_tenant_id": settings.entra_tenant_id,
                    "workload_identity_pool": settings.workload_identity_pool,
                    "verified": True,
                },
            )
            report["submitted"] = True
            report["ga_evidence"] = {
                "id": evidence.id,
                "gate_key": evidence.gate_key,
                "evidence_type": evidence.evidence_type,
                "status": evidence.status,
                "content_hash": evidence.content_hash,
            }
            report["error"] = None
            session.commit()
        except Exception as exc:
            report["submitted"] = False
            report["ga_evidence"] = None
            report["error"] = f"{type(exc).__name__}: {exc}"

    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
