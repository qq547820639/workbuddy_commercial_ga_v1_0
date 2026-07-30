"""Shared helpers for release-gate evidence/attestation engines.

The Pilot gate engine (``services.pilot``) and the Commercial GA gate engine
(``services.commercial``) operate on different ORM models but share two purely
mechanical query patterns: collecting the latest verified evidence per type,
and hashing a deterministic snapshot of that evidence. Those patterns live here
so the two engines do not duplicate them. The higher-level gate flows (attest,
evaluate, go/no-go) differ meaningfully between the two engines — GA uses
cryptographic signatures and Pilot uses automatic observation checks — and are
therefore kept in their respective modules.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.services.common import content_hash


def verified_evidence_by_type(
    session: Session, model, program_field, program_id: str, gate_key: str,
) -> dict:
    """Return the latest verified evidence row per ``evidence_type``, keyed by type.

    Rows are ordered by ``observed_at`` descending so the first occurrence wins
    via ``setdefault``, matching the per-engine semantics previously inlined in
    both ``pilot._verified_evidence`` and ``commercial.evaluate_ga_gate``.
    """
    rows = session.scalars(
        select(model).where(
            program_field == program_id,
            model.gate_key == gate_key,
            model.status == "VERIFIED",
        ).order_by(model.observed_at.desc())
    ).all()
    result: dict = {}
    for row in rows:
        result.setdefault(row.evidence_type, row)
    return result


def evidence_snapshot_hash(
    session: Session, model, program_field, program_id: str, gate_key: str,
) -> str:
    """Content hash of all verified evidence for a gate, with deterministic ordering."""
    rows = session.scalars(
        select(model).where(
            program_field == program_id,
            model.gate_key == gate_key,
            model.status == "VERIFIED",
        ).order_by(model.evidence_type, model.observed_at)
    ).all()
    return content_hash([
        {"id": x.id, "type": x.evidence_type, "hash": x.content_hash, "status": x.status}
        for x in rows
    ])
