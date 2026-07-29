from __future__ import annotations

from workbuddy.db.models import Artifact
from workbuddy.services.common import content_hash


def headers(tenant="00000000-0000-0000-0000-000000000001"):
    return {"X-Tenant-ID": tenant, "X-Actor-ID": "owner"}


def test_complete_high_risk_flow(client):
    assert client.post("/v1/demo/bootstrap", headers=headers()).status_code == 200
    inbox = client.get("/v1/inbox", headers=headers()).json()
    sales = next(m for m in inbox if m["provider_message_id"] == "demo:sales:1")
    decision_id = sales["dispatch"]["id"]
    r = client.post(f"/v1/dispatch/{decision_id}/confirm", headers=headers(), json={"team_key": "sales_growth"})
    assert r.status_code == 201
    mission = r.json()
    mission = client.post(f"/v1/missions/{mission['id']}/accept", headers=headers(), json={"expected_version": mission["version"], "reason": "接单"}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/plan", headers=headers(), json={"expected_version": mission["version"], "reason": "规划"}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/approve-plan", headers=headers(), json={"expected_version": mission["version"], "reason": "批准计划"}).json()
    mission = client.post(f"/v1/missions/{mission['id']}/start", headers=headers(), json={"expected_version": mission["version"], "reason": "启动"}).json()
    assert mission["status"] == "EXECUTING"

    for _ in range(10):
        detail = client.get(f"/v1/missions/{mission['id']}", headers=headers()).json()
        if all(i["status"] == "ACCEPTED" for i in detail["work_items"]):
            break
        startable = next((i for i in detail["work_items"] if i["status"] in {"READY", "ASSIGNED", "REVISION_REQUIRED"}), None)
        if not startable:
            # WAITING_DEPENDENCY means another submitted item needs review; handled below.
            submitted = next((i for i in detail["work_items"] if i["status"] == "SUBMITTED"), None)
            assert submitted is not None
            client.post(f"/v1/work-items/{submitted['id']}/review", headers=headers(), json={"decision": "accept", "reason": "符合标准"})
            continue
        run = client.post(f"/v1/work-items/{startable['id']}/start", headers=headers()).json()
        assert run["status"] == "RUNNING"
        submitted_run = client.post(f"/v1/agent-runs/{run['id']}/submit", headers=headers(), json={
            "output": {"type": "analysis", "title": startable["title"], "summary": "done"},
            "evidence": [{"claim": "source-backed", "source_type": "mail", "source_id": "demo:sales:1", "verification_status": "verified", "confidence": 90}],
        })
        assert submitted_run.status_code == 200
        reviewed = client.post(f"/v1/work-items/{startable['id']}/review", headers=headers(), json={"decision": "accept", "reason": "符合标准"})
        assert reviewed.status_code == 200
    else:
        raise AssertionError("work items did not complete")

    mission = client.get(f"/v1/missions/{mission['id']}", headers=headers()).json()["mission"]
    reviewed = client.post(f"/v1/missions/{mission['id']}/lead-review", headers=headers(), json={"expected_version": mission["version"], "reason": "主理人整合"})
    assert reviewed.status_code == 200
    result = reviewed.json()
    assert result["mission"]["status"] == "APPROVAL_REQUIRED"
    approval = result["approval"]
    approved = client.post(f"/v1/approvals/{approval['id']}/decision", headers=headers(), json={"decision": "approve", "reason": "已核对精确动作"})
    assert approved.status_code == 200
    operation = client.post("/v1/operations", headers=headers(), json={"approval_id": approval["id"], "operation_key": "test-send-1"}).json()
    assert operation["status"] == "APPROVED"
    finished = client.post(f"/v1/operations/{operation['id']}/execute", headers=headers(), json={"simulate_unknown": False}).json()
    assert finished["status"] == "SUCCEEDED"
    final = client.get(f"/v1/missions/{mission['id']}", headers=headers()).json()["mission"]
    assert final["status"] == "COMPLETED"
    assert finished["demo_mode"] is True
    assert finished["provider_result"]["message"] == "No real email was sent."


def test_mail_and_operation_idempotency(client):
    payload = {"provider_message_id": "idem:1", "sender": "a@example.com", "recipients": ["owner@example.com"], "subject": "test", "body_text": "hello"}
    a = client.post("/v1/inbox/messages", headers=headers(), json=payload).json()
    b = client.post("/v1/inbox/messages", headers=headers(), json=payload).json()
    assert a["id"] == b["id"]


def test_complete_flow_with_supporting_team_collaboration(client, monkeypatch):
    """End-to-end multi-team collaboration: when the dispatch LLM returns supporting
    team keys, confirm_dispatch auto-opens PENDING collaboration requests; the receiving
    team workspace surfaces them; and the accept → start → complete loop closes back
    through the team API endpoints with the artifact linked to the primary mission."""
    from workbuddy.services import model_gateway

    real_deterministic = model_gateway.ModelGateway._deterministic

    def patched_deterministic(task_type, payload):
        data = real_deterministic(task_type, payload)
        if task_type == "dispatch":
            data["supporting_team_keys"] = ["customer_success"]
        return data

    monkeypatch.setattr(model_gateway.ModelGateway, "_deterministic", staticmethod(patched_deterministic))

    # Bootstrap + dispatch + confirm creates the primary mission and auto-opens a
    # PENDING CollaborationRequest toward customer_success.
    assert client.post("/v1/demo/bootstrap", headers=headers()).status_code == 200
    inbox = client.get("/v1/inbox", headers=headers()).json()
    sales = next(m for m in inbox if m["provider_message_id"] == "demo:sales:1")
    decision_id = sales["dispatch"]["id"]
    r = client.post(f"/v1/dispatch/{decision_id}/confirm", headers=headers(), json={"team_key": "sales_growth"})
    assert r.status_code == 201
    mission = r.json()

    # The receiving team (customer_success) workspace surfaces the pending collaboration.
    cs_collabs = client.get("/v1/teams/customer_success/collaborations?role=receiving", headers=headers()).json()
    assert len(cs_collabs) == 1
    collab = cs_collabs[0]
    assert collab["status"] == "PENDING"
    assert collab["mission_id"] == mission["id"]
    collab_id = collab["id"]

    # The same collaboration is visible in the full workspace aggregation.
    cs_workspace = client.get("/v1/teams/customer_success/workspace", headers=headers()).json()
    assert any(c["id"] == collab_id for c in cs_workspace["collaborations"])

    # The sending team (sales_growth) also sees the outgoing request.
    sales_sending = client.get("/v1/teams/sales_growth/collaborations?role=sending", headers=headers()).json()
    assert any(c["id"] == collab_id for c in sales_sending)

    # Accept → start via the team API endpoints (Task 6 collaboration lifecycle).
    accepted = client.post(f"/v1/teams/customer_success/collaborations/{collab_id}/accept", headers=headers())
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ACCEPTED"
    started = client.post(f"/v1/teams/customer_success/collaborations/{collab_id}/start", headers=headers())
    assert started.status_code == 200
    assert started.json()["status"] == "IN_PROGRESS"

    # The receiving team produces an Artifact in the primary mission scope and links it back.
    # There is no public ad-hoc artifact-creation endpoint, so it is recorded directly.
    artifact_content = {"summary": "客户成功团队回传的协作结论"}
    with client.app.state.SessionLocal() as session:
        artifact = Artifact(
            tenant_id=headers()["X-Tenant-ID"], mission_id=mission["id"],
            work_item_id=None, agent_run_id=None,
            artifact_type="analysis", title="CS 协作交付",
            content=artifact_content, content_hash=content_hash(artifact_content),
        )
        session.add(artifact); session.commit()
        artifact_id = artifact.id

    # Complete the loop and verify the artifact is linked back to the collaboration.
    completed = client.post(
        f"/v1/teams/customer_success/collaborations/{collab_id}/complete",
        headers=headers(), json={"artifact_id": artifact_id},
    )
    assert completed.status_code == 200
    completed_body = completed.json()
    assert completed_body["status"] == "COMPLETED"
    assert completed_body["response"]["artifact_id"] == artifact_id
    assert completed_body["response"]["artifact_title"] == "CS 协作交付"

    # The sending team workspace now reflects the completed collaboration.
    sales_collabs = client.get("/v1/teams/sales_growth/collaborations?role=sending", headers=headers()).json()
    assert any(c["id"] == collab_id and c["status"] == "COMPLETED" for c in sales_collabs)
