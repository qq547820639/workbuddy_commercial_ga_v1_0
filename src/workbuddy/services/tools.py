from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from workbuddy.db.models import (
    AgentRun, MailMessage, Mission, SkillRelease, TeamConstitutionVersion, ToolCall,
    ToolDefinition, ToolGrant,
)
from workbuddy.domain.state_machine import AgentRunStatus
from .audit import append_audit
from .common import content_hash


class ToolPolicyError(ValueError):
    pass


def create_run_grants(session: Session, run: AgentRun) -> list[ToolGrant]:
    skill = session.get(SkillRelease, run.skill_release_id)
    tool_keys = (skill.config if skill else {}).get("tools", [])
    mission = session.get(Mission, run.mission_id)
    constitution = session.get(TeamConstitutionVersion, mission.constitution_version_id) if mission and mission.constitution_version_id else None
    allowed_tools = (constitution.config if constitution else {}).get("allowed_tools")
    if allowed_tools is not None:
        allowed_set = set(allowed_tools)
        tool_keys = [k for k in tool_keys if k in allowed_set]
    grants: list[ToolGrant] = []
    for key in tool_keys:
        tool = session.scalar(select(ToolDefinition).where(ToolDefinition.tenant_id == run.tenant_id, ToolDefinition.tool_key == key))
        if not tool:
            continue
        allowed = list(tool.capabilities)
        grant = ToolGrant(
            tenant_id=run.tenant_id, agent_run_id=run.id, tool_id=tool.id,
            allowed_actions=allowed, data_scope="current_mission", active=True,
        )
        session.add(grant); grants.append(grant)
    return grants


def revoke_run_grants(session: Session, run: AgentRun) -> None:
    for grant in session.scalars(select(ToolGrant).where(ToolGrant.agent_run_id == run.id, ToolGrant.active.is_(True))).all():
        grant.active = False


def invoke_tool(session: Session, tenant_id: str, run_id: str, tool_key: str, action: str, parameters: dict) -> ToolCall:
    run = session.scalar(select(AgentRun).where(AgentRun.id == run_id, AgentRun.tenant_id == tenant_id))
    if not run:
        raise ToolPolicyError("agent run not found")
    if run.status not in {AgentRunStatus.RUNNING.value, AgentRunStatus.TOOL_WAIT.value}:
        raise ToolPolicyError("closed or inactive AgentRun cannot call tools")
    tool = session.scalar(select(ToolDefinition).where(ToolDefinition.tenant_id == tenant_id, ToolDefinition.tool_key == tool_key))
    if not tool:
        raise ToolPolicyError("tool not found")
    grant = session.scalar(select(ToolGrant).where(
        ToolGrant.agent_run_id == run.id, ToolGrant.tool_id == tool.id, ToolGrant.active.is_(True),
    ))
    if not grant or action not in grant.allowed_actions:
        raise ToolPolicyError("tool action is not granted to this AgentRun")
    call = ToolCall(
        tenant_id=tenant_id, agent_run_id=run.id, tool_id=tool.id, action=action,
        parameters_hash=content_hash(parameters), status="EXECUTING",
    )
    session.add(call); session.flush()
    try:
        result = _execute(session, run, tool_key, action, parameters)
        call.status = "SUCCEEDED"; call.result = result
    except Exception as exc:
        call.status = "FAILED"; call.error = str(exc)
        raise
    finally:
        append_audit(session, tenant_id=tenant_id, actor_type="agent", actor_id=f"agent:{run.agent_profile_id}",
                     action="tool.call", aggregate_type="tool_call", aggregate_id=call.id,
                     payload={"agent_run_id": run.id, "tool_key": tool_key, "action": action, "status": call.status,
                              "parameters_hash": call.parameters_hash})
    return call


def _execute(session: Session, run: AgentRun, tool_key: str, action: str, parameters: dict) -> dict:
    if tool_key == "hash_service" and action == "sha256":
        return {"sha256": content_hash(parameters.get("value"))}
    if tool_key == "mail_reader" and action == "read_current_mission_source":
        mission = session.get(Mission, run.mission_id)
        if not mission or mission.source_type != "email":
            return {"source": None}
        message = session.get(MailMessage, mission.source_id)
        if not message or message.tenant_id != run.tenant_id:
            raise ToolPolicyError("mail source is outside the current mission scope")
        return {"message_id": message.id, "sender": message.sender, "subject": message.subject, "body_text": message.body_text}
    if tool_key == "knowledge_reader" and action == "search_authorized_knowledge":
        return {"query": parameters.get("query", ""), "results": [], "notice": "No production knowledge connector is configured; the call is safely empty."}
    if tool_key == "contacts_reader" and action == "lookup_contact":
        return {"query": parameters.get("query", ""), "contacts": [], "notice": "No production contacts connector is configured."}
    if tool_key == "calendar_reader" and action == "find_free_busy":
        return {"participants": parameters.get("participants", []), "slots": [], "notice": "No production calendar connector is configured."}
    if tool_key == "crm_reader" and action == "read_current_customer":
        return {"customer_key": parameters.get("customer_key"), "record": None, "notice": "No production CRM connector is configured."}
    if tool_key == "spreadsheet_engine" and action == "scenario_table":
        scenarios = parameters.get("scenarios", [])
        return {"rows": [{"name": s.get("name"), "value": s.get("revenue", 0) - s.get("cost", 0)} for s in scenarios]}
    raise ToolPolicyError("tool adapter or action is not implemented")
