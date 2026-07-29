#!/usr/bin/env python3
from __future__ import annotations

import argparse, json
from sqlalchemy import select

from workbuddy.db.models import GAReleaseProgram
from workbuddy.db.session import SessionLocal, apply_tenant_context
from workbuddy.services.commercial import ga_go_no_go_report
from workbuddy.settings import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Commercial GA release gates.")
    parser.add_argument("program_id", nargs="?")
    args = parser.parse_args()
    with SessionLocal() as session:
        apply_tenant_context(session, settings.default_tenant_id, local=True)
        program = session.get(GAReleaseProgram, args.program_id) if args.program_id else session.scalar(select(GAReleaseProgram).where(GAReleaseProgram.tenant_id == settings.default_tenant_id).order_by(GAReleaseProgram.created_at.desc()))
        if not program:
            print(json.dumps({"decision": "NO_GO", "blockers": ["No GA release program exists"]}, ensure_ascii=False, indent=2)); return 2
        report = ga_go_no_go_report(session, settings.default_tenant_id, program.id)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0 if report["decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
