from __future__ import annotations

from datetime import date, timedelta

from workbuddy.db.models import MailAccount, SyncRun

TENANT = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Tenant-ID": TENANT, "X-Actor-ID": "owner", "X-Roles": "owner product_owner it_admin security_owner operations_owner privacy_owner platform_owner ai_platform_owner business_owner"}


def _program(client):
    response = client.post("/v1/pilot-programs", headers=HEADERS, json={
        "name": "Production Pilot Test",
        "scope": {"teams": ["sales_growth", "operations_delivery", "customer_success"]},
        "targets": {"stable_mail_days": 5, "dispatch_accuracy_percent": 90},
    })
    assert response.status_code == 201, response.text
    return response.json()


def _verified_evidence(client, program_id, gate, evidence_type):
    created = client.post(f"/v1/pilot-programs/{program_id}/evidence", headers=HEADERS, json={
        "gate_key": gate, "evidence_type": evidence_type, "source": "operator",
        "environment": "production", "metrics": {"passed": True},
    })
    assert created.status_code == 201, created.text
    decided = client.post(f"/v1/pilot-programs/evidence/{created.json()['id']}/decision", headers=HEADERS, json={"decision": "VERIFIED", "reason": "checked"})
    assert decided.status_code == 200, decided.text
    return decided.json()


def test_gate_b_requires_live_observation_evidence_and_attestations(client):
    program = _program(client)
    client.post("/v1/demo/bootstrap", headers=HEADERS)
    inbox = client.get("/v1/inbox", headers=HEADERS).json()
    decision = inbox[0]["dispatch"]
    teams = client.get("/v1/teams", headers=HEADERS).json()
    team = next(t for t in teams if t["id"] == decision["suggested_team_id"])
    feedback = client.post(f"/v1/dispatch/{decision['id']}/feedback", headers=HEADERS, json={
        "confirmed_team_key": team["team_key"], "comment": "correct",
    })
    assert feedback.status_code == 200
    with client.app.state.SessionLocal() as session:
        account = MailAccount(tenant_id=TENANT, provider="gmail", address="pilot@example.com", status="active")
        session.add(account); session.flush()
        session.add(SyncRun(tenant_id=TENANT, account_id=account.id, provider="gmail", sync_type="history", status="SUCCEEDED"))
        session.commit()
    today = date.today()
    for offset in range(5):
        result = client.post(f"/v1/pilot-programs/{program['id']}/metrics", headers=HEADERS, json={
            "metric_date": (today - timedelta(days=offset)).isoformat(), "metrics": {"stable": True},
        })
        assert result.status_code == 201
    for evidence_type in ("cursor_recovery_drill", "mail_sync_stability", "dispatch_accuracy", "risk_recall"):
        _verified_evidence(client, program["id"], "B", evidence_type)
    for role in ("product_owner", "it_admin"):
        signed = client.post(f"/v1/pilot-programs/{program['id']}/attestations", headers=HEADERS, json={
            "gate_key": "B", "role": role, "decision": "APPROVE", "notes": "approved",
        })
        assert signed.status_code == 201, signed.text
    status = client.get(f"/v1/pilot-programs/{program['id']}/gates/B", headers=HEADERS).json()
    assert status["ready"] is True
    assert status["observations"]["stable_days"] == 5


def test_attestation_is_invalidated_when_evidence_snapshot_changes(client):
    program = _program(client)
    evidence = _verified_evidence(client, program["id"], "C", "model_data_agreement")
    signed = client.post(f"/v1/pilot-programs/{program['id']}/attestations", headers=HEADERS, json={
        "gate_key": "C", "role": "product_owner", "decision": "APPROVE", "notes": "signed current snapshot",
    })
    assert signed.status_code == 201
    replacement = _verified_evidence(client, program["id"], "C", "model_data_agreement")
    assert replacement["content_hash"] == evidence["content_hash"]  # immutable content can be identical, row set still changes snapshot
    status = client.get(f"/v1/pilot-programs/{program['id']}/gates/C", headers=HEADERS).json()
    assert "product_owner" in status["missing_attestations"]


def test_go_no_go_is_no_go_until_all_gates_and_production_evidence_pass(client):
    program = _program(client)
    report = client.get(f"/v1/pilot-programs/{program['id']}/go-no-go", headers=HEADERS)
    assert report.status_code == 200
    data = report.json()
    assert data["decision"] == "NO_GO"
    assert set(data["gates"]) == {"B", "C", "D", "PRODUCTION"}
    assert data["blockers"]


def test_pilot_incident_blocks_production_report(client):
    program = _program(client)
    incident = client.post(f"/v1/pilot-programs/{program['id']}/incidents", headers=HEADERS, json={
        "severity": "P1", "category": "security", "title": "Cross-customer access suspected", "details": {"confirmed": False},
    })
    assert incident.status_code == 201
    report = client.get(f"/v1/pilot-programs/{program['id']}/go-no-go", headers=HEADERS).json()
    assert "Open P0/P1 incident exists" in report["blockers"]


def test_ops_preflight_and_prometheus_are_available(client):
    preflight = client.get("/v1/ops/preflight", headers=HEADERS)
    assert preflight.status_code == 200
    assert "checks" in preflight.json()
    metrics = client.get("/metrics/prometheus", headers=HEADERS)
    assert metrics.status_code == 200
    assert "workbuddy_audit_events_total" in metrics.text


def test_evidence_artifact_upload_is_hashed_and_stored(client):
    program = _program(client)
    response = client.post(
        f"/v1/pilot-programs/{program['id']}/evidence/upload",
        headers=HEADERS,
        data={"gate_key": "B", "evidence_type": "cursor_recovery_drill", "source": "operator", "environment": "production"},
        files={"file": ("recovery.txt", b"cursor recovery passed", "text/plain")},
    )
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["artifact_ref"].startswith("file://")
    assert row["metrics"]["artifact_size"] == len(b"cursor recovery passed")
    assert len(row["metrics"]["artifact_sha256"]) == 64


def test_incident_can_be_resolved_but_resolution_is_audited(client):
    program = _program(client)
    incident = client.post(f"/v1/pilot-programs/{program['id']}/incidents", headers=HEADERS, json={
        "severity": "P1", "category": "operations", "title": "Provider result uncertain", "details": {},
    }).json()
    resolved = client.post(f"/v1/pilot-programs/incidents/{incident['id']}/resolve", headers=HEADERS, json={"resolution": "Provider records checked; no duplicate send."})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"
    audits = client.get("/v1/audit?limit=100", headers=HEADERS).json()
    assert any(x["action"] == "pilot.incident_resolved" for x in audits)


def test_full_synthetic_evidence_can_reach_go_without_faking_configuration(client):
    from workbuddy.db.models import ExternalOperation, Mission, ModelInvocation, QualityEvaluation
    from workbuddy.services.common import utcnow

    program = _program(client)
    client.post(f"/v1/pilot-programs/{program['id']}/transition", headers=HEADERS, json={"target": "ACTIVE"})
    client.post("/v1/demo/bootstrap", headers=HEADERS)
    inbox = client.get("/v1/inbox", headers=HEADERS).json()
    decision = inbox[0]["dispatch"]
    teams = client.get("/v1/teams", headers=HEADERS).json()
    team = next(t for t in teams if t["id"] == decision["suggested_team_id"])
    client.post(f"/v1/dispatch/{decision['id']}/feedback", headers=HEADERS, json={"confirmed_team_key": team["team_key"], "comment": "correct"})
    with client.app.state.SessionLocal() as session:
        account = MailAccount(tenant_id=TENANT, provider="gmail", address="go@example.com", status="active", send_enabled=True)
        session.add(account); session.flush()
        session.add(SyncRun(tenant_id=TENANT, account_id=account.id, provider="gmail", sync_type="history", status="SUCCEEDED"))
        mission = Mission(tenant_id=TENANT, source_type="test", source_id="go-mission", title="Verified live send", objective="test", status="COMPLETED")
        session.add(mission); session.flush()
        session.add(ExternalOperation(
            tenant_id=TENANT, mission_id=mission.id, operation_key="verified-live-go", operation_type="email_send",
            status="SUCCEEDED", parameters={}, parameters_hash="x" * 64, demo_mode=False, verified_at=utcnow(),
        ))
        session.add(ModelInvocation(
            tenant_id=TENANT, task_type="agent_execute", provider="test", model_name="test-model", status="SUCCEEDED",
            input_hash="a" * 64, output_hash="b" * 64, usage={}, latency_ms=1, cost_cny_fen=0,
        ))
        session.add(QualityEvaluation(
            tenant_id=TENANT, evaluation_type="pilot", score=100, passed=True, metrics={"evidence_coverage": 100}, evaluator="test",
        ))
        session.commit()
    today = date.today()
    for offset in range(5):
        client.post(f"/v1/pilot-programs/{program['id']}/metrics", headers=HEADERS, json={
            "metric_date": (today - timedelta(days=offset)).isoformat(), "metrics": {"stable": True},
        })
    requirements = client.get("/v1/pilot-programs/schema", headers=HEADERS).json()["gates"]
    for gate, spec in requirements.items():
        for evidence_type in spec["required_evidence"]:
            _verified_evidence(client, program["id"], gate, evidence_type)
        for role in spec["required_roles"]:
            signed = client.post(f"/v1/pilot-programs/{program['id']}/attestations", headers=HEADERS, json={
                "gate_key": gate, "role": role, "decision": "APPROVE", "notes": "synthetic validated evidence",
            })
            assert signed.status_code == 201, signed.text
    report = client.get(f"/v1/pilot-programs/{program['id']}/go-no-go", headers=HEADERS).json()
    assert report["decision"] == "GO", report
