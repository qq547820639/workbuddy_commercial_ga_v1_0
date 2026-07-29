from __future__ import annotations

from collections import defaultdict
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    AgentProfile, Artifact, CollaborationRequest, MemoryRecord, Mission, SkillRelease,
    TeamDefinition, WorkItem, WorkItemDependency,
)
from .audit import append_audit


class GovernanceError(ValueError):
    pass


def update_work_item(session: Session, tenant_id: str, item_id: str, expected_version: int, changes: dict, actor_id: str) -> WorkItem:
    item = session.scalar(select(WorkItem).where(WorkItem.id == item_id, WorkItem.tenant_id == tenant_id))
    if not item:
        raise GovernanceError("work item not found")
    mission = session.get(Mission, item.mission_id)
    if mission.status != "PLANNING":
        raise GovernanceError("work items can only be edited while the mission is PLANNING")
    if item.version != expected_version:
        raise GovernanceError("work item version conflict")
    if "assigned_agent_profile_id" in changes:
        agent = session.scalar(select(AgentProfile).where(
            AgentProfile.id == changes["assigned_agent_profile_id"], AgentProfile.tenant_id == tenant_id,
            AgentProfile.team_id == mission.primary_team_id, AgentProfile.status == "active",
        ))
        if not agent:
            raise GovernanceError("agent profile is not an active member of the primary team")
    if "skill_release_id" in changes:
        skill = session.scalar(select(SkillRelease).where(
            SkillRelease.id == changes["skill_release_id"], SkillRelease.tenant_id == tenant_id,
            SkillRelease.status == "published",
        ))
        if not skill:
            raise GovernanceError("published skill release not found")
    if "acceptance_criteria" in changes and not changes["acceptance_criteria"]:
        raise GovernanceError("work item must retain at least one acceptance criterion")
    allowed = {"title", "objective", "assigned_agent_profile_id", "skill_release_id", "acceptance_criteria", "evidence_requirements"}
    for key, value in changes.items():
        if key in allowed and value is not None:
            setattr(item, key, value)
    item.version += 1
    mission.plan_version += 1; mission.version += 1
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
                 action="work_item.edited", aggregate_type="work_item", aggregate_id=item.id,
                 aggregate_version=item.version, payload={"changed_fields": sorted(k for k in changes if k in allowed), "plan_version": mission.plan_version})
    return item


def add_dependency(session: Session, tenant_id: str, mission_id: str, work_item_id: str, depends_on_id: str, actor_id: str) -> WorkItemDependency:
    mission = session.scalar(select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id))
    if not mission or mission.status != "PLANNING":
        raise GovernanceError("dependencies can only be edited while the mission is PLANNING")
    if work_item_id == depends_on_id:
        raise GovernanceError("work item cannot depend on itself")
    items = session.scalars(select(WorkItem).where(WorkItem.mission_id == mission_id)).all()
    ids = {i.id for i in items}
    if work_item_id not in ids or depends_on_id not in ids:
        raise GovernanceError("both work items must belong to the mission")
    existing = session.scalar(select(WorkItemDependency).where(WorkItemDependency.work_item_id == work_item_id, WorkItemDependency.depends_on_id == depends_on_id))
    if existing:
        return existing
    edges = [(d.depends_on_id, d.work_item_id) for d in session.scalars(select(WorkItemDependency).where(WorkItemDependency.tenant_id == tenant_id, WorkItemDependency.work_item_id.in_(ids))).all()]
    edges.append((depends_on_id, work_item_id))
    if _has_cycle(ids, edges):
        raise GovernanceError("dependency would create a cycle")
    dep = WorkItemDependency(tenant_id=tenant_id, work_item_id=work_item_id, depends_on_id=depends_on_id)
    session.add(dep); session.flush()
    mission.plan_version += 1; mission.version += 1
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
                 action="work_item.dependency_added", aggregate_type="mission", aggregate_id=mission.id,
                 aggregate_version=mission.version, payload={"work_item_id": work_item_id, "depends_on_id": depends_on_id})
    return dep


def remove_dependency(session: Session, tenant_id: str, dependency_id: str, actor_id: str) -> None:
    dep = session.scalar(select(WorkItemDependency).where(WorkItemDependency.id == dependency_id, WorkItemDependency.tenant_id == tenant_id))
    if not dep:
        raise GovernanceError("dependency not found")
    item = session.get(WorkItem, dep.work_item_id); mission = session.get(Mission, item.mission_id)
    if mission.status != "PLANNING":
        raise GovernanceError("dependencies can only be edited while the mission is PLANNING")
    session.delete(dep); mission.plan_version += 1; mission.version += 1
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
                 action="work_item.dependency_removed", aggregate_type="mission", aggregate_id=mission.id,
                 aggregate_version=mission.version, payload={"dependency_id": dependency_id})


def _has_cycle(nodes: set[str], edges: list[tuple[str, str]]) -> bool:
    graph = defaultdict(list); indegree = {n: 0 for n in nodes}
    for source, target in edges:
        graph[source].append(target); indegree[target] += 1
    queue = [n for n, degree in indegree.items() if degree == 0]; seen = 0
    while queue:
        node = queue.pop(); seen += 1
        for nxt in graph[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0: queue.append(nxt)
    return seen != len(nodes)


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


def propose_memory(session: Session, tenant_id: str, mission_id: str, memory_type: str, subject_key: str, content: dict, source_artifact_id: str | None, actor_id: str) -> MemoryRecord:
    mission = session.scalar(select(Mission).where(Mission.id == mission_id, Mission.tenant_id == tenant_id))
    if not mission:
        raise GovernanceError("mission not found")
    if source_artifact_id:
        artifact = session.scalar(select(Artifact).where(Artifact.id == source_artifact_id, Artifact.tenant_id == tenant_id, Artifact.mission_id == mission_id))
        if not artifact:
            raise GovernanceError("source artifact is outside the mission")
    record = MemoryRecord(
        tenant_id=tenant_id, mission_id=mission_id, team_id=mission.primary_team_id,
        agent_profile_id=mission.lead_agent_profile_id, memory_type=memory_type, subject_key=subject_key,
        content=content, source_artifact_id=source_artifact_id, status="PROPOSED",
    )
    session.add(record); session.flush()
    append_audit(session, tenant_id=tenant_id, actor_type="agent", actor_id=actor_id,
                 action="memory.proposed", aggregate_type="memory_record", aggregate_id=record.id,
                 payload={"memory_type": memory_type, "subject_key": subject_key})
    return record


def decide_memory(session: Session, tenant_id: str, record_id: str, decision: str, actor_id: str) -> MemoryRecord:
    record = session.scalar(select(MemoryRecord).where(MemoryRecord.id == record_id, MemoryRecord.tenant_id == tenant_id))
    if not record or record.status != "PROPOSED":
        raise GovernanceError("proposed memory record not found")
    record.status = "APPROVED" if decision == "approve" else "REJECTED"
    record.approved_by = actor_id
    append_audit(session, tenant_id=tenant_id, actor_type="user", actor_id=actor_id,
                 action="memory.decided", aggregate_type="memory_record", aggregate_id=record.id,
                 payload={"decision": decision})
    return record
