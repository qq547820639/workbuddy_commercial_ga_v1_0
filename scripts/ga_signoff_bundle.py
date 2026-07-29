#!/usr/bin/env python3
"""Gap 12: GA signoff bundle generator.

Collects every piece of GA signoff evidence into a single auditable JSON bundle:
all GA evidence records, all gate attestations (with their cryptographic
signatures verified), per-gate evaluations, evidence snapshot hashes, and the
go/no-go report. The bundle itself is sealed with a content hash so any later
tampering with a field is detectable. Prints the bundle as JSON.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbuddy.db.models import GAAttestation, GAEvidence, GAReleaseProgram
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.services.commercial import (
    GA_EVIDENCE_REQUIREMENTS,
    evaluate_ga_gate,
    ga_evidence_snapshot_hash,
    ga_go_no_go_report,
)
from workbuddy.services.common import content_hash, utcnow
from workbuddy.services.gate_signing import verify_attestation_signature
from workbuddy.settings import settings


def _resolve_program(session: Session, tenant_id: str, program_id: str | None) -> GAReleaseProgram | None:
    if program_id:
        return session.get(GAReleaseProgram, program_id)
    return session.scalar(
        select(GAReleaseProgram)
        .where(GAReleaseProgram.tenant_id == tenant_id)
        .order_by(GAReleaseProgram.created_at.desc())
    )


def _verify_attestation(att: GAAttestation) -> dict:
    """Verify a single attestation's cryptographic signature."""
    signature_valid = False
    verification_error: str | None = None
    if not att.cryptographic_signature:
        verification_error = "no signature recorded"
    else:
        try:
            signature_valid = verify_attestation_signature(
                role=att.role,
                decision=att.decision,
                snapshot_hash=att.evidence_snapshot_hash,
                actor_id=att.actor_id,
                timestamp=att.signed_at,
                signature=att.cryptographic_signature,
            )
            if not signature_valid:
                verification_error = "signature does not match recorded payload"
        except Exception as exc:
            verification_error = f"{type(exc).__name__}: {exc}"
    return {
        "id": att.id,
        "gate_key": att.gate_key,
        "role": att.role,
        "actor_id": att.actor_id,
        "decision": att.decision,
        "notes": att.notes,
        "evidence_snapshot_hash": att.evidence_snapshot_hash,
        "cryptographic_signature": att.cryptographic_signature,
        "signing_key_id": att.signing_key_id,
        "signed_at": att.signed_at.isoformat() if att.signed_at else None,
        "signature_valid": signature_valid,
        "verification_error": verification_error,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a GA signoff bundle with verified attestations.")
    parser.add_argument("program_id", nargs="?", help="GA release program id (defaults to the latest program).")
    args = parser.parse_args()

    init_db()
    tenant_id = settings.default_tenant_id

    with SessionLocal() as session:
        apply_tenant_context(session, tenant_id, local=True)

        program = _resolve_program(session, tenant_id, args.program_id)
        if not program:
            print(json.dumps({
                "gap": 12,
                "title": "GA signoff bundle",
                "tenant_id": tenant_id,
                "program": None,
                "error": "No GA release program found.",
            }, ensure_ascii=False, indent=2))
            return

        # 1. Collect all evidence records for the program.
        evidence_rows = session.scalars(
            select(GAEvidence).where(
                GAEvidence.ga_program_id == program.id,
            ).order_by(GAEvidence.gate_key, GAEvidence.evidence_type, GAEvidence.observed_at)
        ).all()
        evidence = [
            {
                "id": e.id,
                "gate_key": e.gate_key,
                "evidence_type": e.evidence_type,
                "status": e.status,
                "source": e.source,
                "metrics": e.metrics,
                "artifact_ref": e.artifact_ref,
                "content_hash": e.content_hash,
                "submitted_by": e.submitted_by,
                "verified_by": e.verified_by,
                "verified_at": e.verified_at.isoformat() if e.verified_at else None,
                "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                "rejection_reason": e.rejection_reason,
            }
            for e in evidence_rows
        ]

        # 2. Collect all attestations and verify each cryptographic signature.
        attestation_rows = session.scalars(
            select(GAAttestation).where(
                GAAttestation.ga_program_id == program.id,
            ).order_by(GAAttestation.gate_key, GAAttestation.role)
        ).all()
        attestations = [_verify_attestation(a) for a in attestation_rows]

        # 3. Evaluate every gate and capture its verified evidence snapshot hash.
        gates: dict[str, dict] = {}
        for gate_key in GA_EVIDENCE_REQUIREMENTS:
            try:
                evaluation = evaluate_ga_gate(session, tenant_id, program.id, gate_key)
            except Exception as exc:
                evaluation = {"gate": gate_key, "error": f"{type(exc).__name__}: {exc}", "ready": False}
            snapshot_hash = ga_evidence_snapshot_hash(session, program.id, gate_key)
            gates[gate_key] = {**evaluation, "evidence_snapshot_hash": snapshot_hash}

        # 4. Produce the go/no-go report.
        try:
            go_no_go = ga_go_no_go_report(session, tenant_id, program.id)
        except Exception as exc:
            go_no_go = {"error": f"{type(exc).__name__}: {exc}"}

        # 5. Seal the bundle with a content hash over its core fields.
        bundle_core = {
            "program_id": program.id,
            "program_name": program.name,
            "program_status": program.status,
            "evidence_count": len(evidence),
            "attestation_count": len(attestations),
            "valid_signatures": sum(1 for a in attestations if a["signature_valid"]),
            "gates": {k: {"ready": v.get("ready"), "snapshot": v.get("evidence_snapshot_hash")} for k, v in gates.items()},
            "decision": go_no_go.get("decision"),
        }
        bundle_hash = content_hash(bundle_core)

        bundle = {
            "gap": 12,
            "title": "GA signoff bundle",
            "tenant_id": tenant_id,
            "generated_at": utcnow().isoformat(),
            "program": {
                "id": program.id,
                "name": program.name,
                "status": program.status,
                "owner_id": program.owner_id,
                "pilot_program_id": program.pilot_program_id,
                "version": program.version,
            },
            "evidence": evidence,
            "attestations": attestations,
            "gates": gates,
            "go_no_go": go_no_go,
            "signature_verification": {
                "total_attestations": len(attestations),
                "valid_signatures": sum(1 for a in attestations if a["signature_valid"]),
                "invalid_signatures": sum(1 for a in attestations if not a["signature_valid"]),
            },
            "bundle_core": bundle_core,
            "bundle_hash": bundle_hash,
        }

    print(json.dumps(bundle, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
