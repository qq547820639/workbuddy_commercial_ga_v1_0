from __future__ import annotations

from sqlalchemy import select

from workbuddy.db.models import Artifact, CollaborationRequest, Mission, TeamDefinition
from workbuddy.domain.state_machine import CollaborationRequestStatus
from workbuddy.services.business import (
    BusinessError,
    accept_collaboration,
    complete_collaboration_with_artifact,
    decline_collaboration,
    get_collaboration_artifacts,
    start_collaboration_work,
)

TENANT = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Tenant-ID": TENANT, "X-Actor-ID": "owner"}


def _bootstrap_mission(client):
    client.post("/v1/demo/bootstrap", headers=HEADERS)
    sales = next(x for x in client.get("/v1/inbox", headers=HEADERS).json() if x["provider_message_id"] == "demo:sales:1")
    mission = client.post(f"/v1/dispatch/{sales['dispatch']['id']}/confirm", headers=HEADERS, json={"team_key": "sales_growth"}).json()
    return mission


def _make_pending_collaboration(session, mission_id, sending_team_id, receiving_team_id, objective="协助处理商务子任务"):
    request = CollaborationRequest(
        tenant_id=TENANT, mission_id=mission_id,
        sending_team_id=sending_team_id, receiving_team_id=receiving_team_id,
        objective=objective, input_scope={"source": "test"},
        expected_artifact="支持团队的调查结果或交付物",
        status=CollaborationRequestStatus.PENDING.value,
    )
    session.add(request); session.flush()
    return request


def _team_id(session, team_key):
    return session.scalar(select(TeamDefinition).where(TeamDefinition.tenant_id == TENANT, TeamDefinition.team_key == team_key)).id


def test_auto_create_collaboration_on_dispatch_confirm(client, monkeypatch):
    """When the LLM returns supporting_team_keys, confirm_dispatch auto-opens PENDING requests."""
    from workbuddy.services import model_gateway

    real_deterministic = model_gateway.ModelGateway._deterministic

    def patched_deterministic(task_type, payload):
        data = real_deterministic(task_type, payload)
        if task_type == "dispatch":
            data["supporting_team_keys"] = ["customer_success", "finance_ops"]
        return data

    monkeypatch.setattr(model_gateway.ModelGateway, "_deterministic", staticmethod(patched_deterministic))

    mission = _bootstrap_mission(client)
    with client.app.state.SessionLocal() as session:
        rows = session.scalars(select(CollaborationRequest).where(CollaborationRequest.mission_id == mission["id"]).order_by(CollaborationRequest.created_at)).all()
        assert len(rows) == 2
        receiving_keys = {
            session.get(TeamDefinition, r.receiving_team_id).team_key for r in rows
        }
        assert receiving_keys == {"customer_success", "finance_ops"}
        for r in rows:
            assert r.status == CollaborationRequestStatus.PENDING.value
            assert r.sending_team_id == _team_id(session, "sales_growth")
            assert r.expected_artifact == "支持团队的调查结果或交付物"
            assert r.objective.startswith("协助处理 ") and r.objective.endswith(" 相关子任务")


def test_collaboration_accept_start_complete_lifecycle(client):
    mission = _bootstrap_mission(client)
    with client.app.state.SessionLocal() as session:
        sales_id = _team_id(session, "sales_growth")
        cs_id = _team_id(session, "customer_success")
        request = _make_pending_collaboration(session, mission["id"], sales_id, cs_id)

        accepted = accept_collaboration(session, request.id, "agent:cs-lead")
        assert accepted.status == CollaborationRequestStatus.ACCEPTED.value

        started = start_collaboration_work(session, request.id)
        assert started.status == CollaborationRequestStatus.IN_PROGRESS.value

        artifact = Artifact(
            tenant_id=TENANT, mission_id=mission["id"], work_item_id=None, agent_run_id=None,
            artifact_type="analysis", title="CS 协作调查结果",
            content={"summary": "客户成功团队交付"}, content_hash="deadbeef",
        )
        session.add(artifact); session.flush()

        completed = complete_collaboration_with_artifact(session, request.id, artifact.id, "agent:cs-lead")
        assert completed.status == CollaborationRequestStatus.COMPLETED.value
        assert completed.response["artifact_id"] == artifact.id
        assert completed.response_reason is not None
        session.commit()

        deliverables = get_collaboration_artifacts(session, mission["id"])
        assert len(deliverables) == 1
        assert deliverables[0]["artifact_id"] == artifact.id
        assert deliverables[0]["artifact"]["title"] == "CS 协作调查结果"
        assert deliverables[0]["receiving_team_id"] == cs_id


def test_collaboration_decline_records_reason(client):
    mission = _bootstrap_mission(client)
    with client.app.state.SessionLocal() as session:
        sales_id = _team_id(session, "sales_growth")
        ops_id = _team_id(session, "operations_delivery")
        request = _make_pending_collaboration(session, mission["id"], sales_id, ops_id)

        declined = decline_collaboration(session, request.id, "agent:ops-lead", "团队当前无可用容量")
        assert declined.status == CollaborationRequestStatus.DECLINED.value
        assert declined.response_reason == "团队当前无可用容量"
        session.commit()


def test_invalid_collaboration_transitions_rejected(client):
    mission = _bootstrap_mission(client)
    with client.app.state.SessionLocal() as session:
        sales_id = _team_id(session, "sales_growth")
        hr_id = _team_id(session, "hr_people")
        request = _make_pending_collaboration(session, mission["id"], sales_id, hr_id)

        # Cannot start work before accepting.
        try:
            start_collaboration_work(session, request.id)
        except BusinessError as exc:
            assert "cannot start" in str(exc)
        else:
            raise AssertionError("start before accept must fail")

        accepted = accept_collaboration(session, request.id, "agent:hr-lead")
        started = start_collaboration_work(session, request.id)

        # Cannot accept again once in progress.
        try:
            accept_collaboration(session, request.id, "agent:hr-lead")
        except BusinessError as exc:
            assert "cannot be accepted" in str(exc)
        else:
            raise AssertionError("accept from IN_PROGRESS must fail")

        # Cannot complete without an artifact.
        try:
            complete_collaboration_with_artifact(session, request.id, "nonexistent-artifact", "agent:hr-lead")
        except BusinessError as exc:
            assert "artifact not found" in str(exc)
        else:
            raise AssertionError("completing with missing artifact must fail")

        assert started.status == CollaborationRequestStatus.IN_PROGRESS.value
        session.commit()


def test_decline_from_accepted_state_allowed(client):
    mission = _bootstrap_mission(client)
    with client.app.state.SessionLocal() as session:
        sales_id = _team_id(session, "sales_growth")
        finance_id = _team_id(session, "finance_ops")
        request = _make_pending_collaboration(session, mission["id"], sales_id, finance_id)
        accept_collaboration(session, request.id, "agent:finance-lead")
        declined = decline_collaboration(session, request.id, "agent:finance-lead", "接受后发现资源不足")
        assert declined.status == CollaborationRequestStatus.DECLINED.value
        assert declined.response_reason == "接受后发现资源不足"
        session.commit()
