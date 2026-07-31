from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import Artifact, CollaborationRequest, Mission, TeamDefinition
from workbuddy.domain.state_machine import CollaborationRequestStatus
from ._transitions import BusinessError, _collaboration_transition
from .audit import append_audit
from .common import model_dict
from .governance import GovernanceError


def _get_collaboration(session: Session, collaboration_id: str) -> CollaborationRequest:
    request = session.scalar(select(CollaborationRequest).where(CollaborationRequest.id == collaboration_id))
    if not request:
        raise BusinessError("collaboration request not found")
    return request


def request_collaboration(session: Session, tenant_id: str, mission_id: str, receiving_team_key: str, objective: str, expected_artifact: str, input_scope: dict, actor_id: str) -> CollaborationRequest:
    mission = session.scalar(select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id))
    receiving = session.scalar(select(TeamDefinition).where(TeamDefinition.tenant_id == tenant_id, TeamDefinition.team_key == receiving_team_key))
    if not mission or not receiving:
        raise GovernanceError("mission or receiving team not found")
    if receiving.id == mission.primary_team_id:
        raise GovernanceError("collaboration team must differ from the primary team")
    request = CollaborationRequest(
        tenant_id=tenant_id, mission_id=mission.id, sending_team_id=mission.primary_team_id,
        receiving_team_id=receiving.id, objective=objective, input_scope=input_scope,
        expected_artifact=expected_artifact, status="REQUESTED",
    )
    session.add(request); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="agent", actor_id=actor_id,
                 action="collaboration.requested", aggregate_type="collaboration_request", aggregate_id=request.id,
                 payload={"mission_id": mission.id, "receiving_team_id": receiving.id, "input_scope": input_scope})
    return request


def respond_collaboration(session: Session, tenant_id: str, request_id: str, status: str, response: dict, actor_id: str) -> CollaborationRequest:
    request = session.scalar(select(CollaborationRequest).where(CollaborationRequest.id == request_id, CollaborationRequest.tenant_id == tenant_id))
    if not request:
        raise GovernanceError("collaboration request not found")
    if request.status not in {"REQUESTED", "ACCEPTED", "IN_PROGRESS"}:
        raise GovernanceError("collaboration request is closed")
    request.status = status; request.response = response
    append_audit(session, tenant_id=tenant_id, actor_type="agent", actor_id=actor_id,
                 action="collaboration.responded", aggregate_type="collaboration_request", aggregate_id=request.id,
                 payload={"status": status})
    return request


def accept_collaboration(session: Session, collaboration_id: str, actor_id: str) -> CollaborationRequest:
    request = _get_collaboration(session, collaboration_id)
    if request.status != CollaborationRequestStatus.PENDING.value:
        raise BusinessError(f"collaboration request cannot be accepted from {request.status}")
    _collaboration_transition(session, request, CollaborationRequestStatus.ACCEPTED, actor_id, "接收团队接受协作请求")
    return request


def decline_collaboration(session: Session, collaboration_id: str, actor_id: str, reason: str) -> CollaborationRequest:
    request = _get_collaboration(session, collaboration_id)
    if request.status not in {CollaborationRequestStatus.PENDING.value, CollaborationRequestStatus.ACCEPTED.value}:
        raise BusinessError(f"collaboration request cannot be declined from {request.status}")
    _collaboration_transition(session, request, CollaborationRequestStatus.DECLINED, actor_id, reason)
    request.response_reason = reason
    return request


def start_collaboration_work(session: Session, collaboration_id: str) -> CollaborationRequest:
    request = _get_collaboration(session, collaboration_id)
    if request.status != CollaborationRequestStatus.ACCEPTED.value:
        raise BusinessError(f"collaboration request cannot start from {request.status}")
    _collaboration_transition(session, request, CollaborationRequestStatus.IN_PROGRESS, "service", "接收团队开始执行协作子任务")
    return request


def complete_collaboration_with_artifact(session: Session, collaboration_id: str, artifact_id: str, actor_id: str) -> CollaborationRequest:
    request = _get_collaboration(session, collaboration_id)
    if request.status != CollaborationRequestStatus.IN_PROGRESS.value:
        raise BusinessError(f"collaboration request cannot be completed from {request.status}")
    artifact = session.scalar(select(Artifact).where(
        Artifact.id == artifact_id, Artifact.tenant_id == request.tenant_id, Artifact.mission_id == request.mission_id,
    ))
    if not artifact:
        raise BusinessError("artifact not found in collaboration mission scope")
    _collaboration_transition(session, request, CollaborationRequestStatus.COMPLETED, actor_id, "接收团队回传协作 Artifact")
    response = dict(request.response or {})
    response.update({
        "artifact_id": artifact.id,
        "artifact_title": artifact.title,
        "artifact_type": artifact.artifact_type,
    })
    request.response = response
    request.response_reason = "协作完成并已回传 Artifact"
    return request


def get_collaboration_artifacts(session: Session, mission_id: str) -> list[dict[str, Any]]:
    """Return completed collaboration requests and their linked artifacts for a mission.

    The primary team's lead can use this to manually reference supporting-team deliverables
    when planning downstream WorkItems (e.g. by recording the collaboration_id and
    artifact_id in WorkItem.input_snapshot or Evidence).
    """
    requests = session.scalars(select(CollaborationRequest).where(
        CollaborationRequest.mission_id == mission_id,
        CollaborationRequest.status == CollaborationRequestStatus.COMPLETED.value,
    ).order_by(CollaborationRequest.updated_at.desc())).all()
    result: list[dict[str, Any]] = []
    for req in requests:
        artifact_id = (req.response or {}).get("artifact_id") if req.response else None
        artifact = session.get(Artifact, artifact_id) if artifact_id else None
        result.append({
            "collaboration_id": req.id,
            "sending_team_id": req.sending_team_id,
            "receiving_team_id": req.receiving_team_id,
            "objective": req.objective,
            "expected_artifact": req.expected_artifact,
            "status": req.status,
            "artifact_id": artifact_id,
            "artifact": model_dict(artifact) if artifact else None,
        })
    return result
