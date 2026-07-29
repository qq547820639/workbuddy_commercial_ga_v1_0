from __future__ import annotations

import pytest
from sqlalchemy import select
from workbuddy.db.models import (
    AgentProfile, AgentRun, Mission, OutboxEvent, SkillDefinition, SkillRelease,
    TeamConstitutionVersion, TeamDefinition, ToolDefinition, WorkItem,
)
from workbuddy.domain.state_machine import AgentRunStatus
from workbuddy.services.common import content_hash
from workbuddy.services.outbox import publish_batch
from workbuddy.services.tools import ToolPolicyError, create_run_grants, invoke_tool


TENANT_ID = "00000000-0000-0000-0000-000000000001"


def h(): return {"X-Tenant-ID": "00000000-0000-0000-0000-000000000001", "X-Actor-ID": "owner"}


def route_and_plan(client, provider_id, team_key, workflow_key=None):
    client.post("/v1/demo/bootstrap", headers=h())
    msg = next(x for x in client.get("/v1/inbox", headers=h()).json() if x["provider_message_id"] == provider_id)
    mission = client.post(f"/v1/dispatch/{msg['dispatch']['id']}/confirm", headers=h(), json={"team_key": team_key, "workflow_key": workflow_key}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/accept", headers=h(), json={"expected_version": mission["version"], "reason": "accept"}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/plan", headers=h(), json={"expected_version": mission["version"], "reason": "plan", "workflow_key": workflow_key}).json()
    return mission


def test_plan_editor_rejects_cycle(client):
    mission = route_and_plan(client, "demo:sales:1", "sales_growth", "commercial_inquiry")
    detail = client.get(f"/v1/missions/{mission['id']}", headers=h()).json()
    items = detail["work_items"]
    first, last = items[0], items[-1]
    response = client.post(f"/v1/missions/{mission['id']}/dependencies", headers=h(), json={"work_item_id": first["id"], "depends_on_id": last["id"]})
    assert response.status_code == 422
    edit = client.patch(f"/v1/work-items/{first['id']}", headers=h(), json={"expected_version": first["version"], "objective": "edited objective", "acceptance_criteria": ["has evidence"]})
    assert edit.status_code == 200 and edit.json()["objective"] == "edited objective"


def test_tool_gateway_enforces_task_scoped_grant(client):
    mission = route_and_plan(client, "demo:ops:1", "operations_delivery", "supplier_coordination")
    mission = client.post(f"/v1/missions/{mission['id']}/approve-plan", headers=h(), json={"expected_version": mission["version"], "reason": "approve"}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/start", headers=h(), json={"expected_version": mission["version"], "reason": "start"}).json()
    detail = client.get(f"/v1/missions/{mission['id']}", headers=h()).json()
    item = next(i for i in detail["work_items"] if i["item_key"] == "collect_facts")
    run = client.post(f"/v1/work-items/{item['id']}/start", headers=h()).json()
    grants = client.get(f"/v1/agent-runs/{run['id']}/tools", headers=h()).json()
    assert any(x["tool"]["tool_key"] == "mail_reader" for x in grants)
    call = client.post(f"/v1/agent-runs/{run['id']}/tools/mail_reader/invoke", headers=h(), json={"action": "read_current_mission_source", "parameters": {}})
    assert call.status_code == 200
    assert "产品上线延期风险" in call.json()["result"]["subject"]
    denied = client.post(f"/v1/agent-runs/{run['id']}/tools/hash_service/invoke", headers=h(), json={"action": "sha256", "parameters": {"value": "x"}})
    assert denied.status_code == 422
    client.post(f"/v1/agent-runs/{run['id']}/submit", headers=h(), json={"output": {"title": "done"}, "evidence": []})
    closed = client.post(f"/v1/agent-runs/{run['id']}/tools/mail_reader/invoke", headers=h(), json={"action": "read_current_mission_source", "parameters": {}})
    assert closed.status_code == 422


def test_outbox_failure_can_be_replayed(client):
    client.post("/v1/demo/bootstrap", headers=h())
    with client.app.state.SessionLocal() as session:
        first = publish_batch(session, fail_event_type="mail.message_ingested", tenant_id=h()["X-Tenant-ID"])
        assert first["failed"] >= 1
        pending = session.scalars(select(OutboxEvent).where(OutboxEvent.published_at.is_(None))).all()
        assert pending
        second = publish_batch(session, tenant_id=h()["X-Tenant-ID"])
        assert second["published"] >= 1


def _build_whitelist_run(session, constitution_config):
    team = TeamDefinition(tenant_id=TENANT_ID, team_key="tools_whitelist_team", name="Tools Whitelist Team")
    session.add(team); session.flush()
    constitution = TeamConstitutionVersion(
        tenant_id=TENANT_ID, team_id=team.id, version=1, status="published",
        config=constitution_config, content_hash=content_hash(constitution_config),
    )
    session.add(constitution); session.flush()
    for key, caps in [("mail.read", ["read"]), ("mail.send", ["send"])]:
        session.add(ToolDefinition(tenant_id=TENANT_ID, tool_key=key, name=key, risk_level="low", capabilities=caps))
    session.flush()
    skill_def = SkillDefinition(tenant_id=TENANT_ID, skill_key="whitelist-test-skill", name="Whitelist Test Skill")
    session.add(skill_def); session.flush()
    skill_cfg = {"name": "Whitelist Test Skill", "tools": ["mail.read", "mail.send"]}
    skill = SkillRelease(
        tenant_id=TENANT_ID, skill_id=skill_def.id, semantic_version="1.0.0",
        status="published", config=skill_cfg, content_hash=content_hash(skill_cfg),
    )
    session.add(skill); session.flush()
    profile = AgentProfile(tenant_id=TENANT_ID, team_id=team.id, role_key="whitelist_tester", name="Whitelist Tester")
    session.add(profile); session.flush()
    mission = Mission(
        tenant_id=TENANT_ID, source_type="manual", source_id="whitelist-test",
        title="whitelist test", objective="verify team-level tool whitelist",
        primary_team_id=team.id, constitution_version_id=constitution.id,
    )
    session.add(mission); session.flush()
    item = WorkItem(
        tenant_id=TENANT_ID, mission_id=mission.id, item_key="whitelist_step",
        title="whitelist step", objective="step", skill_release_id=skill.id,
    )
    session.add(item); session.flush()
    run = AgentRun(
        tenant_id=TENANT_ID, mission_id=mission.id, work_item_id=item.id,
        agent_profile_id=profile.id, skill_release_id=skill.id,
        status=AgentRunStatus.RUNNING.value, data_scope="current_mission",
    )
    session.add(run); session.flush()
    return run


def test_team_allowed_tools_restricts_skill_tools(client):
    constitution_cfg = {"team_key": "tools_whitelist_team", "name": "Tools Whitelist Team", "allowed_tools": ["mail.read"]}
    with client.app.state.SessionLocal() as session:
        run = _build_whitelist_run(session, constitution_cfg)
        grants = create_run_grants(session, run)
        session.flush()
        granted_keys = {t.tool_key for t in session.scalars(
            select(ToolDefinition).where(ToolDefinition.id.in_([g.tool_id for g in grants]))
        ).all()}
        assert granted_keys == {"mail.read"}
        with pytest.raises(ToolPolicyError):
            invoke_tool(session, TENANT_ID, run.id, "mail.send", "send", {})


def test_team_without_allowed_tools_keeps_full_skill_tools(client):
    constitution_cfg = {"team_key": "tools_whitelist_team", "name": "Tools Whitelist Team"}
    with client.app.state.SessionLocal() as session:
        run = _build_whitelist_run(session, constitution_cfg)
        grants = create_run_grants(session, run)
        session.flush()
        granted_keys = {t.tool_key for t in session.scalars(
            select(ToolDefinition).where(ToolDefinition.id.in_([g.tool_id for g in grants]))
        ).all()}
        assert granted_keys == {"mail.read", "mail.send"}
