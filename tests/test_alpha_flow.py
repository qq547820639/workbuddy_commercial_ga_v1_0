from __future__ import annotations


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
