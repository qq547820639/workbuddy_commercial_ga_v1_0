from __future__ import annotations

from sqlalchemy import select
from workbuddy.db.models import Mission, OutboxEvent
from workbuddy.services.outbox import publish_batch


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
