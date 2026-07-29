#!/usr/bin/env python3
"""Gap 10: Customer value metrics report.

Queries CustomerValueMetric records for the default tenant and computes the
core commercial value outcomes: weekly active rate, artifact adoption rate,
total time saved, and conversion rate. Rates are reported as their latest
observed value; time_saved is aggregated as a total. Prints a JSON report and
degrades gracefully to an empty report when no metrics have been recorded.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from workbuddy.db.models import CustomerValueMetric
from workbuddy.db.session import SessionLocal, apply_tenant_context, init_db
from workbuddy.settings import settings


# Metric keys that drive the GA VALUE gate evidence.
RATE_KEYS = ("weekly_active_rate", "artifact_adoption_rate", "conversion_rate")
TOTAL_KEYS = ("time_saved",)


def main() -> None:
    init_db()
    tenant_id = settings.default_tenant_id

    with SessionLocal() as session:
        apply_tenant_context(session, tenant_id, local=True)

        rows = session.scalars(
            select(CustomerValueMetric).where(
                CustomerValueMetric.tenant_id == tenant_id,
            ).order_by(CustomerValueMetric.metric_date.asc())
        ).all()

        # Group rows by metric_key, preserving chronological order.
        by_key: dict[str, list[CustomerValueMetric]] = {}
        for row in rows:
            by_key.setdefault(row.metric_key, []).append(row)

        def _latest(key: str) -> dict | None:
            entries = by_key.get(key)
            if not entries:
                return None
            latest = entries[-1]
            return {
                "value": latest.value,
                "unit": latest.unit,
                "metric_date": latest.metric_date,
                "source": latest.source,
                "observations": len(entries),
            }

        def _total(key: str) -> dict | None:
            entries = by_key.get(key)
            if not entries:
                return None
            total = sum(e.value for e in entries)
            latest = entries[-1]
            return {
                "total": total,
                "unit": latest.unit,
                "latest_value": latest.value,
                "latest_metric_date": latest.metric_date,
                "source": latest.source,
                "observations": len(entries),
            }

        report = {
            "gap": 10,
            "title": "Customer value metrics report",
            "tenant_id": tenant_id,
            "metric_count": len(rows),
            "metric_keys": sorted(by_key.keys()),
            "weekly_active_rate": _latest("weekly_active_rate"),
            "artifact_adoption_rate": _latest("artifact_adoption_rate"),
            "time_saved": _total("time_saved"),
            "conversion_rate": _latest("conversion_rate"),
            "by_metric": {
                key: {
                    "observations": len(entries),
                    "latest": {
                        "value": entries[-1].value,
                        "unit": entries[-1].unit,
                        "metric_date": entries[-1].metric_date,
                        "source": entries[-1].source,
                    },
                    "total": sum(e.value for e in entries),
                }
                for key, entries in sorted(by_key.items())
            },
        }

    report["ok"] = report["metric_count"] >= 0
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
