#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy.orm import Session

from workbuddy.db.session import apply_tenant_context, make_engine
from workbuddy.services.pilot import go_no_go_report
from workbuddy.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("program_id")
    parser.add_argument("--out", default="var/go_no_go_report.json")
    args = parser.parse_args()
    with Session(make_engine()) as session:
        apply_tenant_context(session, settings.default_tenant_id)
        report = go_no_go_report(session, settings.default_tenant_id, args.program_id)
    path = Path(args.out); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["decision"] == "GO" else 3)


if __name__ == "__main__":
    main()
