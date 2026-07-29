from __future__ import annotations

from sqlalchemy import select

from workbuddy.db.models import (
    AgentProfile, AgentRun, CollaborationRequest, Mission, TeamConstitutionVersion,
    TeamDefinition,
)
from workbuddy.domain.state_machine import CollaborationRequestStatus

TENANT = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Tenant-ID": TENANT, "X-Actor-ID": "owner"}


def _bootstrap_mission(client):
    """Bootstrap the demo inbox and confirm dispatch for the sales_growth team.

    Returns the freshly routed Mission dict (status ROUTED, counted as in-progress).
    """
    client.post("/v1/demo/bootstrap", headers=HEADERS)
    sales = next(x for x in client.get("/v1/inbox", headers=HEADERS).json() if x["provider_message_id"] == "demo:sales:1")
    return client.post(f"/v1/dispatch/{sales['dispatch']['id']}/confirm", headers=HEADERS, json={"team_key": "sales_growth"}).json()


def _team_id(session, team_key):
    return session.scalar(select(TeamDefinition).where(
        TeamDefinition.tenant_id == TENANT, TeamDefinition.team_key == team_key,
    )).id


def test_team_dashboard_returns_aggregated_metrics(client):
    mission = _bootstrap_mission(client)

    dashboard = client.get("/v1/teams/sales_growth/dashboard", headers=HEADERS).json()
    # Contract fields are all present.
    for key in (
        "lead_agent", "mission", "in_progress_missions_count",
        "active_workitems_count", "pending_approvals_count", "last_updated_at",
    ):
        assert key in dashboard, f"dashboard missing {key}"
    # The freshly routed mission is in-progress (ROUTED is in IN_PROGRESS_MISSION_STATUSES).
    assert dashboard["in_progress_missions_count"] >= 1
    # sales_growth has a published constitution with a mission statement.
    assert dashboard["mission"] == "将商业来信转化为可验证、可审批、可跟进的增长行动，同时保护利润和承诺边界。"
    # The commercial_director lead agent is seeded.
    assert dashboard["lead_agent"] == "商务主理人"
    # No work items have been started yet, and no approvals are pending at ROUTED stage.
    assert dashboard["active_workitems_count"] == 0
    assert dashboard["pending_approvals_count"] == 0
    assert dashboard["last_updated_at"] is not None


def test_team_workspace_returns_full_aggregation(client):
    mission = _bootstrap_mission(client)

    workspace = client.get("/v1/teams/sales_growth/workspace", headers=HEADERS).json()
    for key in ("team", "constitution", "members", "missions", "skills", "collaborations", "memories", "last_updated_at"):
        assert key in workspace, f"workspace missing {key}"

    assert workspace["team"]["team_key"] == "sales_growth"
    assert workspace["team"]["name"] == "销售与商务增长专家团"
    assert workspace["team"]["active"] is True
    assert workspace["team"]["mission"] == workspace["team"]["mission"]  # published constitution mission

    # Published constitution summary is surfaced.
    assert workspace["constitution"] is not None
    assert workspace["constitution"]["status"] == "published"
    assert "version" in workspace["constitution"]
    assert "content_hash" in workspace["constitution"]

    # Members include the lead (long-term AgentProfile records).
    members = workspace["members"]
    assert members, "members should not be empty"
    leads = [m for m in members if m["is_lead"]]
    assert len(leads) == 1
    assert leads[0]["role_key"] == "commercial_director"

    # The routed mission appears in the in-progress mission list.
    missions = workspace["missions"]
    assert any(m["id"] == mission["id"] for m in missions)
    listed = next(m for m in missions if m["id"] == mission["id"])
    assert listed["status"] == "ROUTED"
    assert "workitem_progress" in listed

    # Skills usable by the team are surfaced.
    assert workspace["skills"], "skills should not be empty"

    # Collaborations and memories are lists (empty until created).
    assert isinstance(workspace["collaborations"], list)
    assert isinstance(workspace["memories"], list)
    assert workspace["last_updated_at"] is not None


def test_team_missions_filter_active_vs_all(client):
    active_mission = _bootstrap_mission(client)

    with client.app.state.SessionLocal() as session:
        team_id = _team_id(session, "sales_growth")
        constitution = session.scalar(select(TeamConstitutionVersion).where(
            TeamConstitutionVersion.team_id == team_id,
            TeamConstitutionVersion.status == "published",
        ).order_by(TeamConstitutionVersion.version.desc()).limit(1))
        # A finished mission is no longer in-progress and must be filtered out by default.
        completed = Mission(
            tenant_id=TENANT, source_type="manual", source_id="workspace-filter-completed",
            title="已完成的协作任务", objective="历史任务，用于验证 active 过滤",
            risk_level="low", status="COMPLETED", primary_team_id=team_id,
            constitution_version_id=constitution.id,
        )
        session.add(completed); session.commit()
        completed_id = completed.id

    active_only = client.get("/v1/teams/sales_growth/missions?status_filter=active", headers=HEADERS).json()
    active_ids = {m["id"] for m in active_only}
    assert active_mission["id"] in active_ids
    assert completed_id not in active_ids, "COMPLETED mission must be excluded from active filter"

    all_missions = client.get("/v1/teams/sales_growth/missions?status_filter=all", headers=HEADERS).json()
    all_ids = {m["id"] for m in all_missions}
    assert active_mission["id"] in all_ids
    assert completed_id in all_ids, "COMPLETED mission must appear under status_filter=all"
    assert len(all_ids) >= len(active_ids)


def test_team_collaborations_filter_by_role(client):
    mission = _bootstrap_mission(client)
    with client.app.state.SessionLocal() as session:
        sales_id = _team_id(session, "sales_growth")
        cs_id = _team_id(session, "customer_success")
        ops_id = _team_id(session, "operations_delivery")
        # sales_growth is the SENDING team toward customer_success.
        sending = CollaborationRequest(
            tenant_id=TENANT, mission_id=mission["id"],
            sending_team_id=sales_id, receiving_team_id=cs_id,
            objective="sales 向 cs 发起协作", input_scope={"source": "test"},
            expected_artifact="客户背景结论", status=CollaborationRequestStatus.PENDING.value,
        )
        # operations_delivery is the SENDING team toward sales_growth (sales is receiving).
        receiving = CollaborationRequest(
            tenant_id=TENANT, mission_id=mission["id"],
            sending_team_id=ops_id, receiving_team_id=sales_id,
            objective="ops 向 sales 发起协作", input_scope={"source": "test"},
            expected_artifact="交付风险结论", status=CollaborationRequestStatus.PENDING.value,
        )
        session.add_all([sending, receiving]); session.commit()
        sending_id, receiving_id = sending.id, receiving.id

    sending_rows = client.get("/v1/teams/sales_growth/collaborations?role=sending", headers=HEADERS).json()
    sending_ids = {r["id"] for r in sending_rows}
    assert sending_ids == {sending_id}, "role=sending must return only requests where the team is the sender"

    receiving_rows = client.get("/v1/teams/sales_growth/collaborations?role=receiving", headers=HEADERS).json()
    receiving_ids = {r["id"] for r in receiving_rows}
    assert receiving_ids == {receiving_id}, "role=receiving must return only requests where the team is the receiver"

    all_rows = client.get("/v1/teams/sales_growth/collaborations?role=all", headers=HEADERS).json()
    all_ids = {r["id"] for r in all_rows}
    assert {sending_id, receiving_id} <= all_ids, "role=all must include both sending and receiving requests"


def test_subagent_lifecycle_visible_in_workspace(client):
    """A CLOSED AgentRun is a one-shot execution whose context is destroyed, while the
    long-term AgentProfile persists as a team member. The workspace API must surface the
    persistent profile (members) and the run's effect (workitem_progress) without leaking
    the destroyed run context as a member.
    """
    mission = _bootstrap_mission(client)
    # Drive the mission far enough to create and close a one-shot AgentRun.
    mission = client.post(f"/v1/missions/{mission['id']}/accept", headers=HEADERS, json={"expected_version": mission["version"], "reason": "接单"}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/plan", headers=HEADERS, json={"expected_version": mission["version"], "reason": "规划"}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/approve-plan", headers=HEADERS, json={"expected_version": mission["version"], "reason": "批准计划"}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/start", headers=HEADERS, json={"expected_version": mission["version"], "reason": "启动"}).json()
    detail = client.get(f"/v1/missions/{mission['id']}", headers=HEADERS).json()
    # Pick the first startable work item (READY, no dependencies blocking).
    startable = next(i for i in detail["work_items"] if i["status"] == "READY")
    run = client.post(f"/v1/work-items/{startable['id']}/start", headers=HEADERS).json()
    submitted = client.post(f"/v1/agent-runs/{run['id']}/submit", headers=HEADERS, json={
        "output": {"type": "analysis", "title": startable["title"], "summary": "一次性运行已交付"},
        "evidence": [{"claim": "来源邮件已核对", "source_type": "mail", "source_id": "demo:sales:1", "verification_status": "verified", "confidence": 90}],
    })
    assert submitted.status_code == 200

    # The one-shot AgentRun is CLOSED with its temporary context destroyed.
    with client.app.state.SessionLocal() as session:
        run_obj = session.get(AgentRun, run["id"])
        assert run_obj.status == "CLOSED"
        assert run_obj.context_cleared is True
        assert run_obj.close_reason == "output_saved_and_temporary_context_cleared"
        run_profile_id = run_obj.agent_profile_id

    workspace = client.get("/v1/teams/sales_growth/workspace", headers=HEADERS).json()

    # The long-term AgentProfile that executed the run still persists as a team member.
    members = workspace["members"]
    assert members, "members must list long-term AgentProfiles"

    with client.app.state.SessionLocal() as session:
        run_profile = session.get(AgentProfile, run_profile_id)
        assert run_profile is not None
        # The persistent AgentProfile that owned the run is present in the workspace members.
        assert any(m["role_key"] == run_profile.role_key for m in members), (
            "the long-term AgentProfile that ran the one-shot AgentRun must remain a workspace member"
        )

    # The one-shot run's effect is visible via workitem_progress on its mission, but the
    # run itself is not surfaced as a member (members are AgentProfiles, not AgentRuns).
    listed = next(m for m in workspace["missions"] if m["id"] == mission["id"])
    assert listed["workitem_progress"]["total"] >= 1
    # SUBMITTED is not ACCEPTED, so completed stays 0 until review; the run is closed regardless.
    assert listed["workitem_progress"]["completed"] == 0
