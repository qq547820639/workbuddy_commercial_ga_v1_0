#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from workbuddy.db.session import apply_tenant_context, make_engine
from workbuddy.services.pilot import submit_evidence
from workbuddy.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit immutable gate evidence metadata.")
    parser.add_argument("program_id")
    parser.add_argument("gate", choices=["B", "C", "D", "PRODUCTION"])
    parser.add_argument("evidence_type")
    parser.add_argument("--metrics", default="{}", help="JSON object or @path.json")
    parser.add_argument("--artifact-ref")
    parser.add_argument("--source", default="operator")
    parser.add_argument("--environment", default="production")
    parser.add_argument("--actor", default="operator")
    args = parser.parse_args()
    raw = Path(args.metrics[1:]).read_text(encoding="utf-8") if args.metrics.startswith("@") else args.metrics
    metrics = json.loads(raw)
    engine = make_engine()
    with Session(engine) as session:
        apply_tenant_context(session, settings.default_tenant_id)
        row = submit_evidence(
            session, settings.default_tenant_id, args.program_id, args.actor,
            gate_key=args.gate, evidence_type=args.evidence_type, source=args.source,
            environment=args.environment, metrics=metrics, artifact_ref=args.artifact_ref,
        )
        session.commit(); print(json.dumps({"id": row.id, "status": row.status, "content_hash": row.content_hash}, indent=2))


if __name__ == "__main__":
    main()
