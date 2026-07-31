from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import AgentProfile, AgentRun, MailMessage, Mission, ModelInvocation, SkillDefinition, SkillRelease, WorkItem
from workbuddy.domain.state_machine import AgentRunStatus, WorkItemStatus
from ._transitions import BusinessError, _run_transition, _work_transition
from .mission_service import submit_agent_run
from .common import model_dict, utcnow
from .model_gateway import ModelGateway, agent_output_schema
from .tools import revoke_run_grants


def execute_agent_run(session: Session, tenant_id: str, run_id: str, gateway: ModelGateway | None = None) -> AgentRun:
    gateway = gateway or ModelGateway()
    run = session.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id))
    if not run:
        raise BusinessError("agent run not found")
    if run.status != AgentRunStatus.RUNNING.value:
        raise BusinessError("agent run is not running")
    mission = session.get(Mission, run.mission_id)
    item = session.get(WorkItem, run.work_item_id)
    agent = session.get(AgentProfile, run.agent_profile_id)
    release = session.get(SkillRelease, run.skill_release_id)
    skill = session.get(SkillDefinition, release.skill_id) if release else None
    source = None
    if mission and mission.source_type == "email":
        source = session.get(MailMessage, mission.source_id)
    payload = {
        "mission": model_dict(mission) if mission else {},
        "work_item": model_dict(item) if item else {},
        "agent_profile": model_dict(agent) if agent else {},
        "skill": {"name": skill.name if skill else "Unknown Skill", "release": release.config if release else {}},
        "source": model_dict(source) if source else {},
        "security_boundary": {
            "untrusted_content": ["source.body_text", "source.body_html"],
            "external_write_allowed": False,
            "data_scope": run.data_scope,
        },
    }
    run.started_at = run.started_at or utcnow()
    try:
        result = gateway.complete_structured(
            session,
            tenant_id=tenant_id,
            task_type="agent_execute",
            payload=payload,
            schema=agent_output_schema(),
            mission_id=run.mission_id,
            agent_run_id=run.id,
            prompt_version="agent-execute-v1",
        )
        run.model_invocation_id = result.invocation.id
        submitted = submit_agent_run(session, tenant_id, run.id, result.data["artifact"], result.data["evidence"])
        submitted.finished_at = utcnow()
        from .commercial import record_usage
        record_usage(session, tenant_id, metric_key="agent_runs", quantity=1, unit="run", source_type="agent_run", source_id=run.id, idempotency_key=f"agent-run:{run.id}:completed")
        return submitted
    except Exception as exc:
        # Persist the failed invocation and close the temporary context instead of
        # letting the request rollback all failure evidence. The WorkItem becomes
        # BLOCKED so the lead can inspect and explicitly create a new AgentRun.
        invocation = session.scalar(select(ModelInvocation).where(
            ModelInvocation.tenant_id == tenant_id,
            ModelInvocation.agent_run_id == run.id,
        ).order_by(ModelInvocation.created_at.desc()).limit(1))
        if invocation:
            run.model_invocation_id = invocation.id
        run.output = {"error_type": type(exc).__name__, "error": str(exc), "retryable_via_new_run": True}
        _run_transition(session, run, AgentRunStatus.FAILED, f"agent:{run.agent_profile_id}", "model or execution failure")
        revoke_run_grants(session, run)
        run.context_cleared = True
        run.close_reason = f"failed:{type(exc).__name__}"
        run.finished_at = utcnow()
        _run_transition(session, run, AgentRunStatus.CLOSED, f"agent:{run.agent_profile_id}", "failed run closed and temporary context cleared")
        if item and item.status == WorkItemStatus.RUNNING.value:
            _work_transition(session, item, WorkItemStatus.BLOCKED, "agent-runtime", "AgentRun failed; lead review or explicit retry is required")
        return run
