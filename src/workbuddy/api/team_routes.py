from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from workbuddy.api.deps import actor_id, db_session, tenant_id
from workbuddy.db.models import (
    AgentProfile, ApprovalRequest, CollaborationRequest, MemoryRecord, Mission,
    SkillDefinition, SkillRelease, TeamConstitutionVersion, TeamDefinition, WorkItem,
)
from workbuddy.services.business import (
    accept_collaboration, approve_constitution, complete_collaboration_with_artifact,
    create_constitution_draft, decline_collaboration, publish_constitution,
    start_collaboration_work, submit_constitution_for_review,
)
from workbuddy.services.common import model_dict, naive_utc

router = APIRouter(prefix="/v1/teams", tags=["expert-team-workspace"])

# Missions that are still in flight (not yet completed/failed/cancelled).
IN_PROGRESS_MISSION_STATUSES = [
    "ROUTED", "LEAD_TRIAGE", "PLANNING", "READY", "EXECUTING",
    "LEAD_REVIEW", "APPROVAL_REQUIRED", "APPROVED", "ACTION_EXECUTING", "VERIFYING",
]

# Work items currently being worked on by an agent.
ACTIVE_WORKITEM_STATUSES = ["ASSIGNED", "RUNNING", "SUBMITTED"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConstitutionDraftIn(_Strict):
    config: dict[str, Any]


class CollaborationDeclineIn(_Strict):
    reason: str = Field(min_length=1, max_length=2000)


class CollaborationCompleteIn(_Strict):
    artifact_id: str


def _resolve_team(session: Session, tid: str, team_key: str) -> TeamDefinition:
    team = session.scalar(select(TeamDefinition).where(
        TeamDefinition.tenant_id == tid, TeamDefinition.team_key == team_key,
    ))
    if not team:
        raise HTTPException(404, "team not found")
    return team


def _latest_published_constitution(session: Session, team_id: str) -> TeamConstitutionVersion | None:
    return session.scalar(select(TeamConstitutionVersion).where(
        TeamConstitutionVersion.team_id == team_id, TeamConstitutionVersion.status == "published",
    ).order_by(TeamConstitutionVersion.version.desc()).limit(1))


def _latest_constitution(session: Session, team_id: str) -> TeamConstitutionVersion | None:
    published = _latest_published_constitution(session, team_id)
    if published:
        return published
    return session.scalar(select(TeamConstitutionVersion).where(
        TeamConstitutionVersion.team_id == team_id,
    ).order_by(TeamConstitutionVersion.version.desc()).limit(1))


def _constitution_summary(constitution: TeamConstitutionVersion | None) -> dict[str, Any] | None:
    if not constitution:
        return None
    return {
        "version": constitution.version,
        "status": constitution.status,
        "config": constitution.config,
        "content_hash": constitution.content_hash,
    }


def _team_mission_statement(session: Session, team: TeamDefinition) -> str | None:
    constitution = _latest_constitution(session, team.id)
    if not constitution:
        return None
    return (constitution.config or {}).get("mission")


def _workitem_progress(session: Session, mission_id: str) -> dict[str, int]:
    total = session.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.mission_id == mission_id)) or 0
    completed = session.scalar(select(func.count()).select_from(WorkItem).where(
        WorkItem.mission_id == mission_id, WorkItem.status == "ACCEPTED",
    )) or 0
    return {"completed": completed, "total": total}


def _team_skills(session: Session, tid: str, team_id: str) -> list[dict[str, Any]]:
    """Skill releases usable by the team.

    A release is included when its config declares no ``allowed_roles`` (broadly
    available) or when its allowed roles intersect the team's agent roles.
    """
    roles = set(session.scalars(select(AgentProfile.role_key).where(AgentProfile.team_id == team_id)).all())
    rows = session.execute(select(SkillDefinition, SkillRelease).join(
        SkillRelease, SkillRelease.skill_id == SkillDefinition.id,
    ).where(SkillDefinition.tenant_id == tid).order_by(SkillDefinition.name, SkillRelease.semantic_version)).all()
    result: list[dict[str, Any]] = []
    for definition, release in rows:
        allowed = (release.config or {}).get("allowed_roles") or []
        if not allowed or (set(allowed) & roles):
            result.append({"definition": model_dict(definition), "release": model_dict(release)})
    return result


def _latest_team_timestamp(session: Session, tid: str, team_id: str, floor=None):
    """Most recent updated_at across the team's operational data, normalized to naive UTC."""
    candidates: list = []
    if floor is not None:
        candidates.append(floor)
    candidates.append(session.scalar(select(func.max(Mission.updated_at)).where(
        Mission.tenant_id == tid, Mission.primary_team_id == team_id,
    )))
    candidates.append(session.scalar(select(func.max(WorkItem.updated_at)).join(
        Mission, Mission.id == WorkItem.mission_id,
    ).where(WorkItem.tenant_id == tid, Mission.primary_team_id == team_id)))
    candidates.append(session.scalar(select(func.max(ApprovalRequest.updated_at)).join(
        Mission, Mission.id == ApprovalRequest.mission_id,
    ).where(ApprovalRequest.tenant_id == tid, Mission.primary_team_id == team_id)))
    candidates.append(session.scalar(select(func.max(CollaborationRequest.updated_at)).where(
        CollaborationRequest.tenant_id == tid,
        or_(CollaborationRequest.sending_team_id == team_id, CollaborationRequest.receiving_team_id == team_id),
    )))
    candidates.append(session.scalar(select(func.max(MemoryRecord.updated_at)).where(
        MemoryRecord.tenant_id == tid, MemoryRecord.team_id == team_id,
    )))
    valid = [naive_utc(c) for c in candidates if c is not None]
    return max(valid) if valid else None


def _get_team_collaboration(session: Session, tid: str, team: TeamDefinition, collaboration_id: str) -> CollaborationRequest:
    request = session.scalar(select(CollaborationRequest).where(
        CollaborationRequest.tenant_id == tid, CollaborationRequest.id == collaboration_id,
    ))
    if not request or (request.sending_team_id != team.id and request.receiving_team_id != team.id):
        raise HTTPException(404, "collaboration not found for this team")
    return request


def _get_tenant_constitution(session: Session, tid: str, constitution_version_id: str) -> TeamConstitutionVersion:
    constitution = session.scalar(select(TeamConstitutionVersion).where(
        TeamConstitutionVersion.tenant_id == tid, TeamConstitutionVersion.id == constitution_version_id,
    ))
    if not constitution:
        raise HTTPException(404, "constitution version not found")
    return constitution


@router.get("/{team_key}/dashboard")
def team_dashboard(team_key: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    team = _resolve_team(session, tid, team_key)
    in_progress_missions_count = session.scalar(select(func.count()).select_from(Mission).where(
        Mission.tenant_id == tid, Mission.primary_team_id == team.id,
        Mission.status.in_(IN_PROGRESS_MISSION_STATUSES),
    )) or 0
    active_workitems_count = session.scalar(select(func.count()).select_from(WorkItem).join(
        Mission, Mission.id == WorkItem.mission_id,
    ).where(WorkItem.tenant_id == tid, Mission.primary_team_id == team.id, WorkItem.status.in_(ACTIVE_WORKITEM_STATUSES))) or 0
    pending_approvals_count = session.scalar(select(func.count()).select_from(ApprovalRequest).join(
        Mission, Mission.id == ApprovalRequest.mission_id,
    ).where(ApprovalRequest.tenant_id == tid, Mission.primary_team_id == team.id, ApprovalRequest.status == "PENDING")) or 0
    lead = session.scalar(select(AgentProfile).where(
        AgentProfile.team_id == team.id, AgentProfile.is_lead.is_(True),
    ))
    last_updated_at = _latest_team_timestamp(session, tid, team.id, floor=team.updated_at)
    return {
        "team_key": team.team_key,
        "name": team.name,
        "active": team.active,
        "lead_agent": lead.name if lead else None,
        "mission": _team_mission_statement(session, team),
        "in_progress_missions_count": in_progress_missions_count,
        "active_workitems_count": active_workitems_count,
        "pending_approvals_count": pending_approvals_count,
        "last_updated_at": last_updated_at.isoformat() if last_updated_at else None,
    }


@router.get("/{team_key}/workspace")
def team_workspace(team_key: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    team = _resolve_team(session, tid, team_key)
    constitution = _latest_published_constitution(session, team.id)
    members = session.scalars(select(AgentProfile).where(
        AgentProfile.team_id == team.id,
    ).order_by(AgentProfile.is_lead.desc(), AgentProfile.name)).all()
    missions = session.scalars(select(Mission).where(
        Mission.tenant_id == tid, Mission.primary_team_id == team.id,
        Mission.status.in_(IN_PROGRESS_MISSION_STATUSES),
    ).order_by(Mission.updated_at.desc())).all()
    skills = _team_skills(session, tid, team.id)
    collaborations = session.scalars(select(CollaborationRequest).where(
        CollaborationRequest.tenant_id == tid,
        or_(CollaborationRequest.sending_team_id == team.id, CollaborationRequest.receiving_team_id == team.id),
    ).order_by(CollaborationRequest.created_at.desc())).all()
    memories = session.scalars(select(MemoryRecord).where(
        MemoryRecord.tenant_id == tid, MemoryRecord.team_id == team.id,
    ).order_by(MemoryRecord.created_at.desc())).all()
    last_updated_at = _latest_team_timestamp(session, tid, team.id, floor=team.updated_at)
    return {
        "team": {
            "team_key": team.team_key,
            "name": team.name,
            "active": team.active,
            "mission": (constitution.config or {}).get("mission") if constitution else None,
        },
        "constitution": _constitution_summary(constitution),
        "members": [
            {"is_lead": m.is_lead, "role_key": m.role_key, "name": m.name, "status": m.status, "profile": m.profile}
            for m in members
        ],
        "missions": [
            {
                "id": m.id,
                "objective": m.objective,
                "status": m.status,
                "lead_agent_profile_id": m.lead_agent_profile_id,
                "workitem_progress": _workitem_progress(session, m.id),
            }
            for m in missions
        ],
        "skills": skills,
        "collaborations": [model_dict(c) for c in collaborations],
        "memories": [model_dict(x) for x in memories],
        "last_updated_at": last_updated_at.isoformat() if last_updated_at else None,
    }


@router.get("/{team_key}/missions")
def team_missions(
    team_key: str,
    status_filter: str = Query(default="active"),
    tid: str = Depends(tenant_id),
    session: Session = Depends(db_session),
):
    team = _resolve_team(session, tid, team_key)
    query = select(Mission).where(Mission.tenant_id == tid, Mission.primary_team_id == team.id)
    if status_filter != "all":
        query = query.where(Mission.status.in_(IN_PROGRESS_MISSION_STATUSES))
    missions = session.scalars(query.order_by(Mission.updated_at.desc())).all()
    result = []
    for m in missions:
        data = model_dict(m)
        data["workitem_progress"] = _workitem_progress(session, m.id)
        result.append(data)
    return result


@router.get("/{team_key}/collaborations")
def team_collaborations(
    team_key: str,
    role: str = Query(default="all"),
    tid: str = Depends(tenant_id),
    session: Session = Depends(db_session),
):
    team = _resolve_team(session, tid, team_key)
    query = select(CollaborationRequest).where(CollaborationRequest.tenant_id == tid)
    if role == "sending":
        query = query.where(CollaborationRequest.sending_team_id == team.id)
    elif role == "receiving":
        query = query.where(CollaborationRequest.receiving_team_id == team.id)
    else:
        query = query.where(or_(
            CollaborationRequest.sending_team_id == team.id,
            CollaborationRequest.receiving_team_id == team.id,
        ))
    rows = session.scalars(query.order_by(CollaborationRequest.created_at.desc())).all()
    return [model_dict(r) for r in rows]


@router.post("/{team_key}/collaborations/{collaboration_id}/accept")
def collaboration_accept(
    team_key: str, collaboration_id: str,
    tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    team = _resolve_team(session, tid, team_key)
    _get_team_collaboration(session, tid, team, collaboration_id)
    request = accept_collaboration(session, collaboration_id, actor)
    session.commit()
    return model_dict(request)


@router.post("/{team_key}/collaborations/{collaboration_id}/decline")
def collaboration_decline(
    team_key: str, collaboration_id: str, body: CollaborationDeclineIn,
    tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    team = _resolve_team(session, tid, team_key)
    _get_team_collaboration(session, tid, team, collaboration_id)
    request = decline_collaboration(session, collaboration_id, actor, body.reason)
    session.commit()
    return model_dict(request)


@router.post("/{team_key}/collaborations/{collaboration_id}/start")
def collaboration_start(
    team_key: str, collaboration_id: str,
    tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    team = _resolve_team(session, tid, team_key)
    _get_team_collaboration(session, tid, team, collaboration_id)
    request = start_collaboration_work(session, collaboration_id)
    session.commit()
    return model_dict(request)


@router.post("/{team_key}/collaborations/{collaboration_id}/complete")
def collaboration_complete(
    team_key: str, collaboration_id: str, body: CollaborationCompleteIn,
    tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    team = _resolve_team(session, tid, team_key)
    _get_team_collaboration(session, tid, team, collaboration_id)
    request = complete_collaboration_with_artifact(session, collaboration_id, body.artifact_id, actor)
    session.commit()
    return model_dict(request)


@router.post("/{team_key}/constitution/draft", status_code=201)
def constitution_draft(
    team_key: str, body: ConstitutionDraftIn,
    tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    team = _resolve_team(session, tid, team_key)
    draft = create_constitution_draft(session, team.id, body.config, actor)
    session.commit()
    return model_dict(draft)


@router.post("/constitution/{constitution_version_id}/submit-review")
def constitution_submit_review(
    constitution_version_id: str,
    tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    _get_tenant_constitution(session, tid, constitution_version_id)
    constitution = submit_constitution_for_review(session, constitution_version_id, actor)
    session.commit()
    return model_dict(constitution)


@router.post("/constitution/{constitution_version_id}/approve")
def constitution_approve(
    constitution_version_id: str,
    tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    _get_tenant_constitution(session, tid, constitution_version_id)
    constitution = approve_constitution(session, constitution_version_id, actor)
    session.commit()
    return model_dict(constitution)


@router.post("/constitution/{constitution_version_id}/publish")
def constitution_publish(
    constitution_version_id: str,
    tid: str = Depends(tenant_id), actor: str = Depends(actor_id),
    session: Session = Depends(db_session),
):
    _get_tenant_constitution(session, tid, constitution_version_id)
    constitution = publish_constitution(session, constitution_version_id, actor)
    session.commit()
    return model_dict(constitution)


@router.get("/{team_key}/constitutions")
def team_constitutions(team_key: str, tid: str = Depends(tenant_id), session: Session = Depends(db_session)):
    team = _resolve_team(session, tid, team_key)
    rows = session.scalars(select(TeamConstitutionVersion).where(
        TeamConstitutionVersion.team_id == team.id,
    ).order_by(TeamConstitutionVersion.version.desc())).all()
    return [model_dict(r) for r in rows]
