from __future__ import annotations

from sqlalchemy.orm import Session

from workbuddy.db.models import AgentRun, CollaborationRequest, Mission, WorkItem
from workbuddy.domain.state_machine import (
    AGENT_RUN_TRANSITIONS, COLLABORATION_REQUEST_TRANSITIONS, MISSION_TRANSITIONS,
    WORK_ITEM_TRANSITIONS, AgentRunStatus, CollaborationRequestStatus,
    MissionStatus, WorkItemStatus, transition,
)
from .audit import append_audit


class BusinessError(ValueError):
    pass


class ConflictError(BusinessError):
    pass


def _mission_transition(session: Session, mission: Mission, target: MissionStatus, actor: str, reason: str) -> Mission:
    current = MissionStatus(mission.status)
    mission.status = transition(current, target, MISSION_TRANSITIONS).value
    mission.version += 1
    append_audit(session, tenant_id=mission.tenant_id, actor_type="user" if actor == "owner" else "service",
                 actor_id=actor, action=f"mission.{target.value.lower()}", aggregate_type="mission",
                 aggregate_id=mission.id, aggregate_version=mission.version, payload={"from": current.value, "to": target.value, "reason": reason})
    return mission


def _work_transition(session: Session, item: WorkItem, target: WorkItemStatus, actor: str, reason: str) -> WorkItem:
    current = WorkItemStatus(item.status)
    item.status = transition(current, target, WORK_ITEM_TRANSITIONS).value
    item.version += 1
    append_audit(session, tenant_id=item.tenant_id, actor_type="agent" if actor.startswith("agent:") else "service",
                 actor_id=actor, action=f"work_item.{target.value.lower()}", aggregate_type="work_item",
                 aggregate_id=item.id, aggregate_version=item.version, payload={"from": current.value, "to": target.value, "reason": reason})
    return item


def _run_transition(session: Session, run: AgentRun, target: AgentRunStatus, actor: str, reason: str) -> AgentRun:
    current = AgentRunStatus(run.status)
    run.status = transition(current, target, AGENT_RUN_TRANSITIONS).value
    run.version += 1
    append_audit(session, tenant_id=run.tenant_id, actor_type="agent", actor_id=actor,
                 action=f"agent_run.{target.value.lower()}", aggregate_type="agent_run",
                 aggregate_id=run.id, aggregate_version=run.version, payload={"from": current.value, "to": target.value, "reason": reason})
    return run


def _collaboration_transition(session: Session, request: CollaborationRequest, target: CollaborationRequestStatus, actor: str, reason: str) -> CollaborationRequest:
    current = CollaborationRequestStatus(request.status)
    request.status = transition(current, target, COLLABORATION_REQUEST_TRANSITIONS).value
    append_audit(session, tenant_id=request.tenant_id, actor_type="agent" if actor.startswith("agent:") else "service",
                 actor_id=actor, action=f"collaboration.{target.value.lower()}", aggregate_type="collaboration_request",
                 aggregate_id=request.id, payload={"from": current.value, "to": target.value, "reason": reason})
    return request
