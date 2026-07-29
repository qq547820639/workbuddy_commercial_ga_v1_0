from __future__ import annotations

from collections import defaultdict, deque
from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import AgentProfile, SkillDefinition, SkillRelease, WorkItem, WorkItemDependency, WorkflowVersion
from .model_gateway import ModelGateway


class PlanValidationError(ValueError):
    pass


def validate_acyclic(items: list[dict]) -> None:
    keys = {i["key"] for i in items}
    graph: dict[str, list[str]] = defaultdict(list)
    indegree = {k: 0 for k in keys}
    for item in items:
        for dep in item.get("depends_on", []):
            if dep not in keys:
                raise PlanValidationError(f"unknown dependency: {dep}")
            graph[dep].append(item["key"])
            indegree[item["key"]] += 1
    queue = deque([k for k, v in indegree.items() if v == 0])
    visited = 0
    while queue:
        node = queue.popleft(); visited += 1
        for nxt in graph[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)
    if visited != len(keys):
        raise PlanValidationError("work item dependency graph contains a cycle")


def _plan_schema() -> dict:
    item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "key": {"type": "string"},
            "title": {"type": "string"},
            "objective": {"type": "string"},
            "role": {"type": "string"},
            "skill": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "evidence_requirements": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["key", "title", "objective", "role", "skill", "depends_on", "acceptance_criteria", "evidence_requirements"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "work_items": {"type": "array", "items": item},
            "missing_information": {"type": "array", "items": {"type": "string"}},
            "collaboration_suggestions": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["work_items", "missing_information", "collaboration_suggestions"],
    }


def build_plan(session: Session, tenant_id: str, mission_id: str, workflow: WorkflowVersion, team_id: str, objective: str) -> list[WorkItem]:
    workflow_specs = workflow.config.get("work_items", [])
    if not workflow_specs:
        raise PlanValidationError("workflow has no work items")
    result = ModelGateway().complete_structured(
        session,
        tenant_id=tenant_id,
        task_type="mission_plan",
        payload={
            "mission_objective": objective,
            "workflow_key": workflow.workflow_key,
            "workflow_name": workflow.name,
            "workflow_work_items": workflow_specs,
            "constraints": {
                "one_primary_team": True,
                "external_write_requires_owner_approval": True,
                "all_claims_require_evidence": True,
            },
        },
        schema=_plan_schema(),
        mission_id=mission_id,
        prompt_version="mission-plan-v1",
    )
    specs = result.data["work_items"]
    validate_acyclic(specs)
    existing = session.scalars(select(WorkItem).where(WorkItem.mission_id == mission_id)).all()
    if existing:
        for item in existing:
            session.delete(item)
        session.flush()
    created: dict[str, WorkItem] = {}
    for index, spec in enumerate(specs):
        role = spec["role"]
        agent = session.scalar(select(AgentProfile).where(
            AgentProfile.tenant_id == tenant_id,
            AgentProfile.team_id == team_id,
            AgentProfile.role_key == role,
            AgentProfile.status == "active",
        ))
        if not agent:
            raise PlanValidationError(f"no active agent profile for role {role}")
        skill_key, version = spec["skill"].rsplit("@", 1)
        skill = session.scalar(select(SkillDefinition).where(SkillDefinition.tenant_id == tenant_id, SkillDefinition.skill_key == skill_key))
        release = session.scalar(select(SkillRelease).where(
            SkillRelease.skill_id == skill.id if skill else False,
            SkillRelease.semantic_version == version,
            SkillRelease.status == "published",
        )) if skill else None
        if not release:
            raise PlanValidationError(f"published skill release not found: {spec['skill']}")
        item = WorkItem(
            tenant_id=tenant_id, mission_id=mission_id, item_key=spec["key"],
            title=spec["title"], objective=spec["objective"],
            status="DRAFT", assigned_agent_profile_id=agent.id, skill_release_id=release.id,
            sequence=index,
            acceptance_criteria=spec["acceptance_criteria"],
            evidence_requirements=spec["evidence_requirements"],
            input_snapshot={
                "workflow_key": workflow.workflow_key,
                "workflow_version": workflow.version,
                "role": role,
                "skill": spec["skill"],
                "model_invocation_id": result.invocation.id,
            },
        )
        session.add(item); session.flush(); created[spec["key"]] = item
    for spec in specs:
        for dep in spec.get("depends_on", []):
            session.add(WorkItemDependency(
                tenant_id=tenant_id,
                work_item_id=created[spec["key"]].id,
                depends_on_id=created[dep].id,
            ))
    return list(created.values())
