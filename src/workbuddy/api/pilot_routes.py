from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.api.deps import actor_id, actor_roles, db_session, require_tenant, tenant_id
from workbuddy.db.models import (
    GateAttestation, GateEvidence, OperationalDrill, PilotDailyMetric, PilotIncident,
    PilotMailbox, PilotProgram,
)
from workbuddy.services.common import model_dict
from workbuddy.services.object_store import ObjectStoreError, object_store
from workbuddy.services.pilot import (
    GATE_EVIDENCE_REQUIREMENTS, GATE_REQUIRED_ROLES, PilotError, attest_gate,
    complete_drill, create_drill, create_program, evaluate_gate, go_no_go_report,
    record_daily_metric, record_incident, register_mailbox, resolve_incident, submit_evidence,
    transition_program, verify_evidence,
)

router = APIRouter(tags=["production-pilot"])


class PilotProgramIn(BaseModel):
    name: str = Field(min_length=3, max_length=240)
    start_date: str | None = None
    end_date: str | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    targets: dict[str, Any] = Field(default_factory=dict)
    owners: dict[str, str | None] = Field(default_factory=dict)


class TransitionIn(BaseModel):
    target: str


class PilotMailboxIn(BaseModel):
    mail_account_id: str
    mode: str = "SHADOW"
    team_keys: list[str] = Field(default_factory=list)
    allowed_recipient_domains: list[str] = Field(default_factory=list)
    allowed_recipient_addresses: list[str] = Field(default_factory=list)
    daily_send_limit: int = Field(default=0, ge=0, le=1000)


class EvidenceIn(BaseModel):
    gate_key: str
    evidence_type: str
    source: str
    environment: str = "staging"
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifact_ref: str | None = None


class EvidenceDecisionIn(BaseModel):
    decision: str
    reason: str = ""


class MetricIn(BaseModel):
    metric_date: str
    mailbox_id: str | None = None
    metrics: dict[str, Any]
    source: str = "operator"


class DrillIn(BaseModel):
    drill_type: str
    execution_mode: str = "SIMULATED"


class DrillCompleteIn(BaseModel):
    passed: bool
    result: dict[str, Any] = Field(default_factory=dict)
    evidence_id: str | None = None


class AttestationIn(BaseModel):
    gate_key: str
    role: str
    decision: str
    notes: str = ""


class IncidentIn(BaseModel):
    severity: str
    category: str
    title: str
    details: dict[str, Any] = Field(default_factory=dict)


class IncidentResolveIn(BaseModel):
    resolution: str = Field(min_length=3)


@router.get("/v1/pilot-programs/schema")
def pilot_schema():
    return {
        "gates": {
            key: {"required_evidence": list(value), "required_roles": list(GATE_REQUIRED_ROLES[key])}
            for key, value in GATE_EVIDENCE_REQUIREMENTS.items()
        }
    }


@router.get("/v1/pilot-programs")
def list_programs(tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    rows = session.scalars(select(PilotProgram).where(PilotProgram.tenant_id == tid).order_by(PilotProgram.created_at.desc())).all()
    return [model_dict(x) for x in rows]


@router.post("/v1/pilot-programs", status_code=201)
def create_program_route(body: PilotProgramIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    require_tenant(session, tid)
    try:
        row = create_program(session, tid, actor, **body.model_dump()); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/pilot-programs/{program_id}/transition")
def transition_program_route(program_id: str, body: TransitionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = transition_program(session, tid, program_id, actor, body.target); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/v1/pilot-programs/{program_id}")
def get_program(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    program = session.scalar(select(PilotProgram).where(PilotProgram.id == program_id, PilotProgram.tenant_id == tid))
    if not program:
        raise HTTPException(404, "pilot program not found")
    mailboxes = session.scalars(select(PilotMailbox).where(PilotMailbox.pilot_program_id == program_id)).all()
    incidents = session.scalars(select(PilotIncident).where(PilotIncident.pilot_program_id == program_id).order_by(PilotIncident.detected_at.desc())).all()
    return {**model_dict(program), "mailboxes": [model_dict(x) for x in mailboxes], "incidents": [model_dict(x) for x in incidents]}


@router.post("/v1/pilot-programs/{program_id}/mailboxes", status_code=201)
def register_mailbox_route(program_id: str, body: PilotMailboxIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = register_mailbox(
            session, tid, program_id, actor, mail_account_id=body.mail_account_id,
            mode=body.mode, team_keys=body.team_keys,
            allowed_domains=body.allowed_recipient_domains,
            allowed_addresses=body.allowed_recipient_addresses,
            daily_send_limit=body.daily_send_limit,
        )
        return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/v1/pilot-programs/{program_id}/evidence")
def list_evidence(program_id: str, gate: str | None = Query(default=None), tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    query = select(GateEvidence).where(GateEvidence.tenant_id == tid, GateEvidence.pilot_program_id == program_id)
    if gate:
        query = query.where(GateEvidence.gate_key == gate)
    rows = session.scalars(query.order_by(GateEvidence.observed_at.desc())).all()
    return [model_dict(x) for x in rows]


@router.post("/v1/pilot-programs/{program_id}/evidence/upload", status_code=201)
async def upload_evidence_artifact(
    program_id: str, gate_key: str = Form(...), evidence_type: str = Form(...),
    source: str = Form(default="operator"), environment: str = Form(default="production"),
    file: UploadFile = File(...), tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    try:
        data = await file.read()
        if not data:
            raise HTTPException(422, "evidence artifact is empty")
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(413, "evidence artifact exceeds 25 MiB")
        stored = object_store.put(
            tenant_id=tid, namespace=f"pilot-{program_id}/{gate_key}",
            filename=file.filename or "evidence.bin", data=data,
            content_type=file.content_type or "application/octet-stream",
        )
        row = submit_evidence(
            session, tid, program_id, actor, gate_key=gate_key.upper(), evidence_type=evidence_type,
            source=source, environment=environment,
            metrics={"artifact_sha256": stored.sha256, "artifact_size": stored.size, "content_type": stored.content_type},
            artifact_ref=stored.ref,
        )
        return model_dict(row)
    except (PilotError, ObjectStoreError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/pilot-programs/{program_id}/evidence", status_code=201)
def submit_evidence_route(program_id: str, body: EvidenceIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = submit_evidence(session, tid, program_id, actor, **body.model_dump()); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/pilot-programs/evidence/{evidence_id}/decision")
def verify_evidence_route(evidence_id: str, body: EvidenceDecisionIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if not set(roles).intersection({"security_owner", "platform_owner", "privacy_owner", "operations_owner", "product_owner"}):
        raise HTTPException(403, "evidence verification requires an accountable owner role")
    try:
        row = verify_evidence(session, tid, evidence_id, actor, decision=body.decision, reason=body.reason); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/pilot-programs/{program_id}/metrics", status_code=201)
def record_metric_route(program_id: str, body: MetricIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = record_daily_metric(session, tid, program_id, actor, **body.model_dump()); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/v1/pilot-programs/{program_id}/metrics")
def list_metrics(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    rows = session.scalars(select(PilotDailyMetric).where(PilotDailyMetric.tenant_id == tid, PilotDailyMetric.pilot_program_id == program_id).order_by(PilotDailyMetric.metric_date.desc())).all()
    return [model_dict(x) for x in rows]


@router.post("/v1/pilot-programs/{program_id}/drills", status_code=201)
def create_drill_route(program_id: str, body: DrillIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = create_drill(session, tid, program_id, actor, **body.model_dump()); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/v1/pilot-programs/{program_id}/drills")
def list_drills(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    rows = session.scalars(select(OperationalDrill).where(OperationalDrill.tenant_id == tid, OperationalDrill.pilot_program_id == program_id).order_by(OperationalDrill.created_at.desc())).all()
    return [model_dict(x) for x in rows]


@router.post("/v1/pilot-programs/drills/{drill_id}/complete")
def complete_drill_route(drill_id: str, body: DrillCompleteIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = complete_drill(session, tid, drill_id, actor, **body.model_dump()); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/pilot-programs/{program_id}/attestations", status_code=201)
def attest_route(program_id: str, body: AttestationIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), roles: tuple[str, ...] = Depends(actor_roles), session: Session = Depends(db_session)):
    if body.role not in roles:
        raise HTTPException(403, f"token does not contain attestation role {body.role}")
    try:
        row = attest_gate(session, tid, program_id, actor, **body.model_dump()); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/v1/pilot-programs/{program_id}/attestations")
def list_attestations(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    rows = session.scalars(select(GateAttestation).where(GateAttestation.tenant_id == tid, GateAttestation.pilot_program_id == program_id).order_by(GateAttestation.signed_at.desc())).all()
    return [model_dict(x) for x in rows]


@router.get("/v1/pilot-programs/{program_id}/gates/{gate_key}")
def gate_status(program_id: str, gate_key: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    try:
        return evaluate_gate(session, tid, program_id, gate_key.upper())
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/v1/pilot-programs/{program_id}/go-no-go")
def report(program_id: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    try:
        return go_no_go_report(session, tid, program_id)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/pilot-programs/{program_id}/incidents", status_code=201)
def incident_route(program_id: str, body: IncidentIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = record_incident(session, tid, program_id, actor, **body.model_dump()); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/v1/pilot-programs/incidents/{incident_id}/resolve")
def resolve_incident_route(incident_id: str, body: IncidentResolveIn, tid: str = Depends(tenant_id), actor: str = Depends(actor_id), session: Session = Depends(db_session)):
    try:
        row = resolve_incident(session, tid, incident_id, actor, resolution=body.resolution); return model_dict(row)
    except PilotError as exc:
        raise HTTPException(422, str(exc)) from exc
