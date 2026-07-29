from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    DispatchFeedback, ExternalOperation, GateAttestation, GateEvidence, MailAccount,
    ModelInvocation, OperationalDrill, PilotDailyMetric, PilotIncident, PilotMailbox,
    PilotProgram, QualityEvaluation, SyncRun,
)
from workbuddy.services.audit import append_audit
from workbuddy.services.common import content_hash, utcnow


class PilotError(ValueError):
    pass


DEFAULT_TARGETS: dict[str, Any] = {
    "stable_mail_days": 5,
    "dispatch_accuracy_percent": 90,
    "risk_recall_percent": 100,
    "plan_acceptance_percent": 80,
    "evidence_coverage_percent": 100,
    "critical_fact_error_percent_max": 1,
    "duplicate_send_count_max": 0,
    "unapproved_send_count_max": 0,
    "p0_p1_incidents_max": 0,
}

GATE_EVIDENCE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "B": ("cursor_recovery_drill", "mail_sync_stability", "dispatch_accuracy", "risk_recall"),
    "C": ("model_data_agreement", "agent_evaluation", "red_team", "evidence_coverage"),
    "D": ("live_send_verification", "unknown_recovery_drill", "duplicate_send_zero", "unapproved_send_zero"),
    "PRODUCTION": ("penetration_test", "privacy_review", "backup_restore_drill", "incident_response_drill", "support_readiness"),
}

GATE_REQUIRED_ROLES: dict[str, tuple[str, ...]] = {
    "B": ("product_owner", "it_admin"),
    "C": ("product_owner", "ai_platform_owner", "security_owner", "business_owner"),
    "D": ("operations_owner", "security_owner", "product_owner"),
    "PRODUCTION": ("product_owner", "platform_owner", "security_owner", "privacy_owner", "operations_owner"),
}


def create_program(
    session: Session, tenant_id: str, actor_id: str, *, name: str,
    start_date: str | None = None, end_date: str | None = None,
    scope: dict[str, Any] | None = None, targets: dict[str, Any] | None = None,
    owners: dict[str, str | None] | None = None,
) -> PilotProgram:
    existing = session.scalar(select(PilotProgram).where(PilotProgram.tenant_id == tenant_id, PilotProgram.name == name))
    if existing:
        return existing
    owners = owners or {}
    program = PilotProgram(
        tenant_id=tenant_id, name=name, owner_id=actor_id,
        security_owner_id=owners.get("security_owner_id"),
        operations_owner_id=owners.get("operations_owner_id"),
        privacy_owner_id=owners.get("privacy_owner_id"),
        start_date=start_date, end_date=end_date, scope=scope or {},
        targets={**DEFAULT_TARGETS, **(targets or {})},
    )
    session.add(program); session.flush()
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.program_created", aggregate_type="PilotProgram", aggregate_id=program.id,
        payload={"name": name, "scope": program.scope, "targets": program.targets},
    )
    return program


def transition_program(session: Session, tenant_id: str, program_id: str, actor_id: str, target: str) -> PilotProgram:
    program = session.scalar(select(PilotProgram).where(PilotProgram.id == program_id, PilotProgram.tenant_id == tenant_id))
    if not program:
        raise PilotError("pilot program not found")
    allowed = {
        "DRAFT": {"ACTIVE", "CANCELLED"}, "ACTIVE": {"PAUSED", "COMPLETED", "CANCELLED"},
        "PAUSED": {"ACTIVE", "COMPLETED", "CANCELLED"}, "COMPLETED": set(), "CANCELLED": set(),
    }
    if target not in allowed.get(program.status, set()):
        raise PilotError(f"invalid pilot transition {program.status} -> {target}")
    before = program.status; program.status = target; program.version += 1
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.program_transitioned", aggregate_type="PilotProgram", aggregate_id=program.id,
        aggregate_version=program.version, payload={"from": before, "to": target},
    )
    return program


def register_mailbox(
    session: Session, tenant_id: str, program_id: str, actor_id: str, *,
    mail_account_id: str, mode: str = "SHADOW", team_keys: list[str] | None = None,
    allowed_domains: list[str] | None = None, allowed_addresses: list[str] | None = None,
    daily_send_limit: int = 0,
) -> PilotMailbox:
    program = session.scalar(select(PilotProgram).where(PilotProgram.id == program_id, PilotProgram.tenant_id == tenant_id))
    account = session.scalar(select(MailAccount).where(MailAccount.id == mail_account_id, MailAccount.tenant_id == tenant_id))
    if not program or not account:
        raise PilotError("pilot program or mail account not found")
    if mode not in {"SHADOW", "AGENT_DRAFT", "LIVE_SEND"}:
        raise PilotError("invalid pilot mailbox mode")
    if mode == "LIVE_SEND" and not account.send_enabled:
        raise PilotError("mail account does not have send scope")
    row = session.scalar(select(PilotMailbox).where(PilotMailbox.pilot_program_id == program_id, PilotMailbox.mail_account_id == mail_account_id))
    if not row:
        row = PilotMailbox(tenant_id=tenant_id, pilot_program_id=program_id, mail_account_id=mail_account_id)
        session.add(row)
    row.mode = mode; row.team_keys = team_keys or []; row.allowed_recipient_domains = [x.lower() for x in (allowed_domains or [])]
    row.allowed_recipient_addresses = [x.lower() for x in (allowed_addresses or [])]
    row.daily_send_limit = max(0, daily_send_limit); row.status = "ACTIVE"; row.activated_at = utcnow()
    session.flush()
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.mailbox_registered", aggregate_type="PilotMailbox", aggregate_id=row.id,
        payload={"program_id": program_id, "account_id": mail_account_id, "mode": mode},
    )
    return row


def submit_evidence(
    session: Session, tenant_id: str, program_id: str, actor_id: str, *, gate_key: str,
    evidence_type: str, source: str, environment: str, metrics: dict[str, Any],
    artifact_ref: str | None = None, observed_at=None,
) -> GateEvidence:
    if gate_key not in GATE_EVIDENCE_REQUIREMENTS:
        raise PilotError("unknown gate")
    if evidence_type not in GATE_EVIDENCE_REQUIREMENTS[gate_key]:
        raise PilotError(f"evidence type {evidence_type} is not valid for gate {gate_key}")
    material = {"gate": gate_key, "type": evidence_type, "source": source, "environment": environment,
                "metrics": metrics, "artifact_ref": artifact_ref}
    evidence = GateEvidence(
        tenant_id=tenant_id, pilot_program_id=program_id, gate_key=gate_key,
        evidence_type=evidence_type, source=source, environment=environment,
        metrics=metrics, artifact_ref=artifact_ref, content_hash=content_hash(material),
        observed_at=observed_at or utcnow(), submitted_by=actor_id,
    )
    session.add(evidence); session.flush()
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.evidence_submitted", aggregate_type="GateEvidence", aggregate_id=evidence.id,
        payload={"program_id": program_id, "gate": gate_key, "evidence_type": evidence_type, "content_hash": evidence.content_hash},
    )
    return evidence


def verify_evidence(
    session: Session, tenant_id: str, evidence_id: str, actor_id: str, *, decision: str, reason: str = "",
) -> GateEvidence:
    evidence = session.scalar(select(GateEvidence).where(GateEvidence.id == evidence_id, GateEvidence.tenant_id == tenant_id))
    if not evidence:
        raise PilotError("evidence not found")
    if decision not in {"VERIFIED", "REJECTED"}:
        raise PilotError("decision must be VERIFIED or REJECTED")
    evidence.status = decision; evidence.verified_by = actor_id; evidence.verified_at = utcnow()
    evidence.rejection_reason = reason if decision == "REJECTED" else None
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.evidence_verified", aggregate_type="GateEvidence", aggregate_id=evidence.id,
        payload={"decision": decision, "reason": reason},
    )
    return evidence


def record_daily_metric(
    session: Session, tenant_id: str, program_id: str, actor_id: str, *,
    metric_date: str, metrics: dict[str, Any], mailbox_id: str | None = None, source: str = "operator",
) -> PilotDailyMetric:
    try:
        date.fromisoformat(metric_date)
    except ValueError as exc:
        raise PilotError("metric_date must be YYYY-MM-DD") from exc
    row = session.scalar(select(PilotDailyMetric).where(
        PilotDailyMetric.pilot_program_id == program_id,
        PilotDailyMetric.metric_date == metric_date,
        PilotDailyMetric.mailbox_id == mailbox_id,
    ))
    if not row:
        row = PilotDailyMetric(tenant_id=tenant_id, pilot_program_id=program_id, metric_date=metric_date, mailbox_id=mailbox_id)
        session.add(row)
    row.metrics = metrics; row.source = source
    session.flush()
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.daily_metric_recorded", aggregate_type="PilotDailyMetric", aggregate_id=row.id,
        payload={"date": metric_date, "metrics": metrics, "source": source},
    )
    return row


def create_drill(
    session: Session, tenant_id: str, program_id: str, actor_id: str, *,
    drill_type: str, execution_mode: str = "SIMULATED",
) -> OperationalDrill:
    if execution_mode not in {"SIMULATED", "LIVE"}:
        raise PilotError("execution_mode must be SIMULATED or LIVE")
    drill = OperationalDrill(
        tenant_id=tenant_id, pilot_program_id=program_id, drill_type=drill_type,
        execution_mode=execution_mode, status="PLANNED", initiated_by=actor_id,
    )
    session.add(drill); session.flush()
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.drill_created", aggregate_type="OperationalDrill", aggregate_id=drill.id,
        payload={"drill_type": drill_type, "execution_mode": execution_mode},
    )
    return drill


def complete_drill(
    session: Session, tenant_id: str, drill_id: str, actor_id: str, *,
    passed: bool, result: dict[str, Any], evidence_id: str | None = None,
) -> OperationalDrill:
    drill = session.scalar(select(OperationalDrill).where(OperationalDrill.id == drill_id, OperationalDrill.tenant_id == tenant_id))
    if not drill:
        raise PilotError("drill not found")
    drill.status = "PASSED" if passed else "FAILED"; drill.result = result
    drill.started_at = drill.started_at or utcnow(); drill.finished_at = utcnow(); drill.evidence_id = evidence_id
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.drill_completed", aggregate_type="OperationalDrill", aggregate_id=drill.id,
        payload={"passed": passed, "result": result, "evidence_id": evidence_id},
    )
    return drill


def record_incident(
    session: Session, tenant_id: str, program_id: str, actor_id: str, *, severity: str,
    category: str, title: str, details: dict[str, Any] | None = None,
) -> PilotIncident:
    if severity not in {"P0", "P1", "P2", "P3"}:
        raise PilotError("invalid incident severity")
    incident = PilotIncident(
        tenant_id=tenant_id, pilot_program_id=program_id, severity=severity,
        category=category, title=title, details=details or {}, owner_id=actor_id,
    )
    session.add(incident); session.flush()
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.incident_recorded", aggregate_type="PilotIncident", aggregate_id=incident.id,
        payload={"severity": severity, "category": category, "title": title},
    )
    return incident


def resolve_incident(
    session: Session, tenant_id: str, incident_id: str, actor_id: str, *, resolution: str,
) -> PilotIncident:
    incident = session.scalar(select(PilotIncident).where(PilotIncident.id == incident_id, PilotIncident.tenant_id == tenant_id))
    if not incident:
        raise PilotError("incident not found")
    if not resolution.strip():
        raise PilotError("resolution is required")
    incident.status = "RESOLVED"; incident.resolved_at = utcnow()
    incident.details = {**(incident.details or {}), "resolution": resolution, "resolved_by": actor_id}
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.incident_resolved", aggregate_type="PilotIncident", aggregate_id=incident.id,
        payload={"resolution": resolution},
    )
    return incident


def _verified_evidence(session: Session, program_id: str, gate_key: str) -> dict[str, GateEvidence]:
    rows = session.scalars(select(GateEvidence).where(
        GateEvidence.pilot_program_id == program_id, GateEvidence.gate_key == gate_key,
        GateEvidence.status == "VERIFIED",
    ).order_by(GateEvidence.observed_at.desc())).all()
    result: dict[str, GateEvidence] = {}
    for row in rows:
        result.setdefault(row.evidence_type, row)
    return result


def evidence_snapshot_hash(session: Session, program_id: str, gate_key: str) -> str:
    rows = session.scalars(select(GateEvidence).where(
        GateEvidence.pilot_program_id == program_id, GateEvidence.gate_key == gate_key,
        GateEvidence.status == "VERIFIED",
    ).order_by(GateEvidence.evidence_type, GateEvidence.observed_at)).all()
    return content_hash([{"id": x.id, "type": x.evidence_type, "hash": x.content_hash, "status": x.status} for x in rows])


def attest_gate(
    session: Session, tenant_id: str, program_id: str, actor_id: str, *,
    gate_key: str, role: str, decision: str, notes: str = "",
) -> GateAttestation:
    if gate_key not in GATE_REQUIRED_ROLES or role not in GATE_REQUIRED_ROLES[gate_key]:
        raise PilotError("role is not authorized for this gate")
    if decision not in {"APPROVE", "REJECT"}:
        raise PilotError("decision must be APPROVE or REJECT")
    snapshot = evidence_snapshot_hash(session, program_id, gate_key)
    row = session.scalar(select(GateAttestation).where(
        GateAttestation.pilot_program_id == program_id, GateAttestation.gate_key == gate_key,
        GateAttestation.role == role,
    ))
    if not row:
        row = GateAttestation(
            tenant_id=tenant_id, pilot_program_id=program_id, gate_key=gate_key, role=role,
            actor_id=actor_id, decision=decision, notes=notes, evidence_snapshot_hash=snapshot,
        )
        session.add(row)
    else:
        row.actor_id = actor_id; row.decision = decision; row.notes = notes
        row.evidence_snapshot_hash = snapshot; row.signed_at = utcnow()
    session.flush()
    append_audit(
        session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
        action="pilot.gate_attested", aggregate_type="GateAttestation", aggregate_id=row.id,
        payload={"program_id": program_id, "gate": gate_key, "role": role, "decision": decision, "snapshot": snapshot},
    )
    return row


def _automatic_observations(session: Session, tenant_id: str, program_id: str) -> dict[str, Any]:
    successful_syncs = session.scalar(select(func.count()).select_from(SyncRun).where(SyncRun.tenant_id == tenant_id, SyncRun.status == "SUCCEEDED")) or 0
    feedback_total = session.scalar(select(func.count()).select_from(DispatchFeedback).where(DispatchFeedback.tenant_id == tenant_id)) or 0
    feedback_correct = session.scalar(select(func.count()).select_from(DispatchFeedback).where(
        DispatchFeedback.tenant_id == tenant_id,
        DispatchFeedback.suggested_team_id == DispatchFeedback.confirmed_team_id,
    )) or 0
    model_success = session.scalar(select(func.count()).select_from(ModelInvocation).where(ModelInvocation.tenant_id == tenant_id, ModelInvocation.status == "SUCCEEDED")) or 0
    quality_count = session.scalar(select(func.count()).select_from(QualityEvaluation).where(QualityEvaluation.tenant_id == tenant_id)) or 0
    verified_live = session.scalar(select(func.count()).select_from(ExternalOperation).where(
        ExternalOperation.tenant_id == tenant_id, ExternalOperation.status == "SUCCEEDED",
        ExternalOperation.demo_mode.is_(False), ExternalOperation.verified_at.is_not(None),
    )) or 0
    metric_rows = session.scalars(select(PilotDailyMetric).where(PilotDailyMetric.pilot_program_id == program_id)).all()
    stable_days = len({row.metric_date for row in metric_rows if bool((row.metrics or {}).get("stable"))})
    open_p0_p1 = session.scalar(select(func.count()).select_from(PilotIncident).where(
        PilotIncident.pilot_program_id == program_id,
        PilotIncident.severity.in_(["P0", "P1"]), PilotIncident.status != "RESOLVED",
    )) or 0
    return {
        "successful_syncs": successful_syncs,
        "dispatch_reviews": feedback_total,
        "dispatch_accuracy_percent": round((feedback_correct / feedback_total) * 100, 2) if feedback_total else 0,
        "model_invocations": model_success,
        "quality_evaluations": quality_count,
        "verified_live_sends": verified_live,
        "stable_days": stable_days,
        "open_p0_p1_incidents": open_p0_p1,
    }


def evaluate_gate(session: Session, tenant_id: str, program_id: str, gate_key: str) -> dict[str, Any]:
    program = session.scalar(select(PilotProgram).where(PilotProgram.id == program_id, PilotProgram.tenant_id == tenant_id))
    if not program:
        raise PilotError("pilot program not found")
    if gate_key not in GATE_EVIDENCE_REQUIREMENTS:
        raise PilotError("unknown gate")
    evidence = _verified_evidence(session, program_id, gate_key)
    requirements = GATE_EVIDENCE_REQUIREMENTS[gate_key]
    missing_evidence = [x for x in requirements if x not in evidence]
    current_snapshot = evidence_snapshot_hash(session, program_id, gate_key)
    attestations = session.scalars(select(GateAttestation).where(
        GateAttestation.pilot_program_id == program_id, GateAttestation.gate_key == gate_key,
    )).all()
    approval_by_role = {x.role: x for x in attestations if x.decision == "APPROVE" and x.evidence_snapshot_hash == current_snapshot}
    missing_attestations = [x for x in GATE_REQUIRED_ROLES[gate_key] if x not in approval_by_role]
    observations = _automatic_observations(session, tenant_id, program_id)
    targets = {**DEFAULT_TARGETS, **(program.targets or {})}
    automatic_checks: dict[str, bool] = {}
    if gate_key == "B":
        automatic_checks = {
            "successful_sync_observed": observations["successful_syncs"] > 0,
            "dispatch_review_observed": observations["dispatch_reviews"] > 0,
            "stable_days_met": observations["stable_days"] >= int(targets["stable_mail_days"]),
            "dispatch_accuracy_met": observations["dispatch_accuracy_percent"] >= float(targets["dispatch_accuracy_percent"]),
        }
    elif gate_key == "C":
        automatic_checks = {
            "model_execution_observed": observations["model_invocations"] > 0,
            "quality_evaluation_observed": observations["quality_evaluations"] > 0,
        }
    elif gate_key == "D":
        automatic_checks = {"verified_live_send_observed": observations["verified_live_sends"] > 0}
    else:
        automatic_checks = {
            "gate_b_ready": evaluate_gate(session, tenant_id, program_id, "B")["ready"],
            "gate_c_ready": evaluate_gate(session, tenant_id, program_id, "C")["ready"],
            "gate_d_ready": evaluate_gate(session, tenant_id, program_id, "D")["ready"],
            "no_open_p0_p1": observations["open_p0_p1_incidents"] <= int(targets["p0_p1_incidents_max"]),
        }
    evidence_ready = not missing_evidence
    automatic_ready = all(automatic_checks.values())
    attestation_ready = not missing_attestations
    ready = evidence_ready and automatic_ready and attestation_ready
    return {
        "program_id": program_id, "gate": gate_key, "ready": ready,
        "evidence_ready": evidence_ready, "automatic_ready": automatic_ready,
        "attestation_ready": attestation_ready, "required_evidence": list(requirements),
        "verified_evidence": sorted(evidence), "missing_evidence": missing_evidence,
        "required_roles": list(GATE_REQUIRED_ROLES[gate_key]),
        "approved_roles": sorted(approval_by_role), "missing_attestations": missing_attestations,
        "automatic_checks": automatic_checks, "observations": observations,
        "evidence_snapshot_hash": current_snapshot,
    }


def go_no_go_report(session: Session, tenant_id: str, program_id: str) -> dict[str, Any]:
    gates = {key: evaluate_gate(session, tenant_id, program_id, key) for key in ("B", "C", "D", "PRODUCTION")}
    incidents = session.scalars(select(PilotIncident).where(PilotIncident.pilot_program_id == program_id).order_by(PilotIncident.detected_at.desc())).all()
    blockers: list[str] = []
    for key, gate in gates.items():
        if not gate["ready"]:
            blockers.append(f"Gate {key} is not ready")
    if any(x.severity in {"P0", "P1"} and x.status != "RESOLVED" for x in incidents):
        blockers.append("Open P0/P1 incident exists")
    return {
        "program_id": program_id, "decision": "GO" if not blockers else "NO_GO",
        "generated_at": utcnow().isoformat(), "gates": gates, "blockers": blockers,
        "incident_summary": {
            "total": len(incidents),
            "open_p0_p1": sum(x.severity in {"P0", "P1"} and x.status != "RESOLVED" for x in incidents),
        },
        "note": "GO is evidence- and attestation-based. Configuration alone never satisfies a production gate.",
    }


def live_send_pilot_preflight(session: Session, tenant_id: str, account_id: str) -> dict[str, Any]:
    """Require an active pilot mailbox and proven B/C gates before a live-send drill.

    Gate D cannot be fully ready before the first verified live send, so its three
    pre-send safety evidence types are required while live_send_verification is
    collected by the provider-confirmed operation itself.
    """
    program = session.scalar(select(PilotProgram).where(
        PilotProgram.tenant_id == tenant_id, PilotProgram.status == "ACTIVE",
    ).order_by(PilotProgram.created_at.desc()).limit(1))
    if not program:
        raise PilotError("an active Production Pilot program is required for live send")
    mailbox = session.scalar(select(PilotMailbox).where(
        PilotMailbox.tenant_id == tenant_id, PilotMailbox.pilot_program_id == program.id,
        PilotMailbox.mail_account_id == account_id, PilotMailbox.status == "ACTIVE",
        PilotMailbox.mode == "LIVE_SEND",
    ))
    if not mailbox:
        raise PilotError("mail account is not enrolled as an active LIVE_SEND pilot mailbox")
    gate_b = evaluate_gate(session, tenant_id, program.id, "B")
    gate_c = evaluate_gate(session, tenant_id, program.id, "C")
    if not gate_b["ready"] or not gate_c["ready"]:
        raise PilotError("Gate B and Gate C must be ready before the first controlled live-send drill")
    d_evidence = _verified_evidence(session, program.id, "D")
    required_pre_send = {"unknown_recovery_drill", "duplicate_send_zero", "unapproved_send_zero"}
    missing = sorted(required_pre_send - set(d_evidence))
    if missing:
        raise PilotError(f"Gate D pre-send evidence is missing: {', '.join(missing)}")
    open_critical = session.scalar(select(func.count()).select_from(PilotIncident).where(
        PilotIncident.pilot_program_id == program.id,
        PilotIncident.severity.in_(["P0", "P1"]), PilotIncident.status != "RESOLVED",
    )) or 0
    if open_critical:
        raise PilotError("live send is blocked while a P0/P1 pilot incident is open")
    return {"program_id": program.id, "pilot_mailbox_id": mailbox.id, "mode": mailbox.mode}


def record_system_gate_evidence(
    session: Session, tenant_id: str, account_id: str, *, evidence_type: str,
    metrics: dict[str, Any], source: str,
) -> GateEvidence | None:
    program = session.scalar(select(PilotProgram).where(
        PilotProgram.tenant_id == tenant_id, PilotProgram.status == "ACTIVE",
    ).order_by(PilotProgram.created_at.desc()).limit(1))
    if not program:
        return None
    mailbox = session.scalar(select(PilotMailbox).where(
        PilotMailbox.tenant_id == tenant_id, PilotMailbox.pilot_program_id == program.id,
        PilotMailbox.mail_account_id == account_id, PilotMailbox.status == "ACTIVE",
    ))
    if not mailbox or evidence_type not in GATE_EVIDENCE_REQUIREMENTS["D"]:
        return None
    material = {
        "gate": "D", "type": evidence_type, "source": source,
        "environment": "production", "metrics": metrics,
    }
    evidence = GateEvidence(
        tenant_id=tenant_id, pilot_program_id=program.id, gate_key="D",
        evidence_type=evidence_type, source=source, environment="production",
        status="VERIFIED", metrics=metrics, content_hash=content_hash(material),
        observed_at=utcnow(), submitted_by="system", verified_by="system",
        verified_at=utcnow(),
    )
    session.add(evidence); session.flush()
    append_audit(
        session, tenant_id=tenant_id, actor_type="service", actor_id="pilot-evidence-service",
        action="pilot.system_evidence_recorded", aggregate_type="GateEvidence", aggregate_id=evidence.id,
        payload={"program_id": program.id, "gate": "D", "evidence_type": evidence_type, "content_hash": evidence.content_hash},
    )
    return evidence
