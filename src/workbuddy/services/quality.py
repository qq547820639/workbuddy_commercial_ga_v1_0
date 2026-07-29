from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import Artifact, Evidence, QualityEvaluation, WorkItem


class QualityGateError(ValueError):
    pass


def evaluate_work_item(session: Session, tenant_id: str, work_item_id: str, *, persist: bool = True) -> dict[str, Any]:
    item = session.scalar(select(WorkItem).where(WorkItem.id == work_item_id, WorkItem.tenant_id == tenant_id))
    if not item:
        raise QualityGateError("work item not found")
    artifacts = session.scalars(select(Artifact).where(Artifact.work_item_id == item.id, Artifact.tenant_id == tenant_id)).all()
    artifact_ids = [a.id for a in artifacts]
    evidence = session.scalars(select(Evidence).where(Evidence.tenant_id == tenant_id, Evidence.artifact_id.in_(artifact_ids) if artifact_ids else False)).all()
    required = max(1, len(item.evidence_requirements or []) - 1)
    verified = sum(1 for e in evidence if e.verification_status == "verified")
    coverage = min(100, round(verified / required * 100))
    has_artifact = bool(artifacts)
    no_disputed = not any(e.verification_status == "disputed" for e in evidence)
    passed = has_artifact and coverage >= 80 and no_disputed
    score = max(0, min(100, (40 if has_artifact else 0) + round(coverage * 0.6) - (20 if not no_disputed else 0)))
    metrics = {
        "artifact_count": len(artifacts),
        "evidence_count": len(evidence),
        "verified_evidence_count": verified,
        "required_evidence_count": required,
        "evidence_coverage": coverage,
        "has_disputed_evidence": not no_disputed,
        "acceptance_criteria_count": len(item.acceptance_criteria or []),
    }
    if persist:
        session.add(QualityEvaluation(
            tenant_id=tenant_id,
            mission_id=item.mission_id,
            work_item_id=item.id,
            agent_profile_id=item.assigned_agent_profile_id,
            skill_release_id=item.skill_release_id,
            evaluation_type="deterministic_quality_gate",
            score=score,
            passed=passed,
            metrics=metrics,
            evaluator="quality-service",
        ))
    return {"score": score, "passed": passed, "metrics": metrics}


def require_work_item_quality(session: Session, tenant_id: str, work_item_id: str) -> dict[str, Any]:
    result = evaluate_work_item(session, tenant_id, work_item_id, persist=True)
    if not result["passed"]:
        raise QualityGateError(
            f"quality gate failed: evidence coverage={result['metrics']['evidence_coverage']}%, "
            f"artifacts={result['metrics']['artifact_count']}"
        )
    return result


def quality_dashboard(session: Session, tenant_id: str) -> dict[str, Any]:
    rows = session.scalars(select(QualityEvaluation).where(QualityEvaluation.tenant_id == tenant_id).order_by(QualityEvaluation.created_at.desc())).all()
    if not rows:
        return {"evaluations": 0, "pass_rate": None, "average_score": None, "by_type": {}, "recent": []}
    by_type: dict[str, list[QualityEvaluation]] = defaultdict(list)
    for row in rows:
        by_type[row.evaluation_type].append(row)
    return {
        "evaluations": len(rows),
        "pass_rate": round(sum(1 for r in rows if r.passed) / len(rows) * 100, 1),
        "average_score": round(sum(r.score for r in rows) / len(rows), 1),
        "by_type": {
            key: {
                "count": len(group),
                "pass_rate": round(sum(1 for r in group if r.passed) / len(group) * 100, 1),
                "average_score": round(sum(r.score for r in group) / len(group), 1),
            }
            for key, group in by_type.items()
        },
        "recent": [
            {"id": r.id, "mission_id": r.mission_id, "work_item_id": r.work_item_id, "type": r.evaluation_type,
             "score": r.score, "passed": r.passed, "metrics": r.metrics, "created_at": r.created_at}
            for r in rows[:50]
        ],
    }
