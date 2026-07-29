from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select

from workbuddy.db.models import ExternalOperation, MailAccount, Mission, ModelInvocation, ObservationWindow, QualityEvaluation, SyncRun
from workbuddy.services.common import utcnow

TENANT = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Tenant-ID": TENANT, "X-Actor-ID": "owner", "X-Roles": "owner product_owner it_admin security_owner operations_owner privacy_owner platform_owner ai_platform_owner business_owner finance_owner legal_owner support_owner"}


def test_subscription_usage_invoice_and_payment_evidence(client):
    plans = client.get("/v1/commercial/plans", headers=HEADERS)
    assert plans.status_code == 200
    assert {x["plan_key"] for x in plans.json()} == {"starter", "growth", "scale"}
    sub = client.post("/v1/commercial/subscriptions", headers=HEADERS, json={"plan_key": "starter", "billing_cycle": "monthly", "trial_days": 14, "provider": "manual"})
    assert sub.status_code == 201, sub.text
    usage = {"metric_key": "agent_runs", "quantity": 12, "unit": "run", "source_type": "test", "source_id": "a", "idempotency_key": "usage-a"}
    first = client.post("/v1/commercial/usage", headers=HEADERS, json=usage)
    second = client.post("/v1/commercial/usage", headers=HEADERS, json=usage)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    summary = client.get("/v1/commercial/usage", headers=HEADERS).json()
    assert summary["usage"]["agent_runs"]["quantity"] == 12
    invoice = client.post("/v1/commercial/invoices", headers=HEADERS, json={"subscription_id": sub.json()["id"], "tax_rate_basis_points": 0})
    assert invoice.status_code == 201, invoice.text
    opened = client.post(f"/v1/commercial/invoices/{invoice.json()['id']}/transition", headers=HEADERS, json={"target": "OPEN"})
    assert opened.status_code == 200
    no_evidence = client.post(f"/v1/commercial/invoices/{invoice.json()['id']}/transition", headers=HEADERS, json={"target": "PAID"})
    assert no_evidence.status_code == 422
    paid = client.post(f"/v1/commercial/invoices/{invoice.json()['id']}/transition", headers=HEADERS, json={"target": "PAID", "manual_evidence": True})
    assert paid.status_code == 200
    assert paid.json()["status"] == "PAID"


def test_onboarding_cannot_skip_requirements(client):
    row = client.post("/v1/commercial/onboardings", headers=HEADERS, json={"name": "Design Partner A"}).json()
    blocked = client.post(f"/v1/commercial/onboardings/{row['id']}/transition", headers=HEADERS, json={"target": "CONFIGURATION"})
    assert blocked.status_code == 422
    client.patch(f"/v1/commercial/onboardings/{row['id']}/checklist", headers=HEADERS, json={"updates": {
        "business_owner_assigned": True, "data_inventory_complete": True, "approval_matrix_approved": True,
    }})
    advanced = client.post(f"/v1/commercial/onboardings/{row['id']}/transition", headers=HEADERS, json={"target": "CONFIGURATION"})
    assert advanced.status_code == 200
    assert advanced.json()["stage"] == "CONFIGURATION"
    skipped = client.post(f"/v1/commercial/onboardings/{row['id']}/transition", headers=HEADERS, json={"target": "AGENT_DRAFT"})
    assert skipped.status_code == 422


def test_support_sla_and_status_incident_are_audited(client):
    ticket = client.post("/v1/support/tickets", headers=HEADERS, json={"severity": "P1", "category": "mail_sync", "title": "Sync stopped", "description": "No changes received"})
    assert ticket.status_code == 201
    in_progress = client.post(f"/v1/support/tickets/{ticket.json()['id']}/transition", headers=HEADERS, json={"status": "IN_PROGRESS", "assigned_to": "oncall"})
    assert in_progress.status_code == 200
    missing_resolution = client.post(f"/v1/support/tickets/{ticket.json()['id']}/transition", headers=HEADERS, json={"status": "RESOLVED"})
    assert missing_resolution.status_code == 422
    resolved = client.post(f"/v1/support/tickets/{ticket.json()['id']}/transition", headers=HEADERS, json={"status": "RESOLVED", "resolution": "Renewed webhook subscription"})
    assert resolved.status_code == 200
    incident = client.post("/v1/status/incidents", headers=HEADERS, json={"title": "Delayed mail sync", "impact": "minor", "public_message": "We are investigating delayed sync.", "components": ["mail-sync"]})
    assert incident.status_code == 201
    finished = client.post(f"/v1/status/incidents/{incident.json()['id']}/transition", headers=HEADERS, json={"status": "RESOLVED", "public_message": "Sync latency has recovered."})
    assert finished.status_code == 200
    audits = client.get("/v1/audit?limit=100", headers=HEADERS).json()
    assert any(x["action"] == "commercial.support_ticket_created" for x in audits)
    assert any(x["action"] == "commercial.status_incident_updated" for x in audits)


def test_compliance_document_acceptance_binds_content_hash(client):
    body_hash = "a" * 64
    doc = client.post("/v1/compliance/documents", headers=HEADERS, json={"document_key": "terms", "title": "Terms", "version": "1.0", "artifact_ref": "file://terms.md", "content_hash": body_hash})
    assert doc.status_code == 201
    agreement = client.post(f"/v1/compliance/documents/{doc.json()['id']}/accept", headers=HEADERS, json={"evidence": {"method": "admin_acceptance"}})
    assert agreement.status_code == 201
    assert agreement.json()["document_content_hash"] == body_hash


def _pilot_go(client):
    program = client.post("/v1/pilot-programs", headers=HEADERS, json={"name": "GA Linked Pilot", "scope": {}, "targets": {}}).json()
    with client.app.state.SessionLocal() as session:
        account = MailAccount(tenant_id=TENANT, provider="gmail", address="ga@example.com", status="active", send_enabled=True)
        session.add(account); session.flush()
        session.add(SyncRun(tenant_id=TENANT, account_id=account.id, provider="gmail", sync_type="history", status="SUCCEEDED"))
        mission = Mission(tenant_id=TENANT, source_type="test", source_id="ga-mission", title="Verified live send", objective="test", status="COMPLETED")
        session.add(mission); session.flush()
        session.add(ExternalOperation(tenant_id=TENANT, mission_id=mission.id, operation_key="verified-ga-live", operation_type="email_send", status="SUCCEEDED", parameters={}, parameters_hash="x" * 64, demo_mode=False, verified_at=utcnow()))
        session.add(ModelInvocation(tenant_id=TENANT, task_type="agent_execute", provider="test", model_name="test-model", status="SUCCEEDED", input_hash="a" * 64, output_hash="b" * 64, usage={}, latency_ms=1, cost_cny_fen=0))
        session.add(QualityEvaluation(tenant_id=TENANT, evaluation_type="pilot", score=100, passed=True, metrics={"evidence_coverage": 100}, evaluator="test"))
        session.commit()
    client.post("/v1/demo/bootstrap", headers=HEADERS)
    inbox = client.get("/v1/inbox", headers=HEADERS).json()
    decision = inbox[0]["dispatch"]
    teams = client.get("/v1/teams", headers=HEADERS).json()
    team = next(t for t in teams if t["id"] == decision["suggested_team_id"])
    client.post(f"/v1/dispatch/{decision['id']}/feedback", headers=HEADERS, json={"confirmed_team_key": team["team_key"], "comment": "correct"})
    for offset in range(5):
        client.post(f"/v1/pilot-programs/{program['id']}/metrics", headers=HEADERS, json={"metric_date": (date.today() - timedelta(days=offset)).isoformat(), "metrics": {"stable": True}})
    spec = client.get("/v1/pilot-programs/schema", headers=HEADERS).json()["gates"]
    for gate, req in spec.items():
        for evidence_type in req["required_evidence"]:
            evidence = client.post(f"/v1/pilot-programs/{program['id']}/evidence", headers=HEADERS, json={"gate_key": gate, "evidence_type": evidence_type, "source": "test", "environment": "production", "metrics": {"passed": True}}).json()
            client.post(f"/v1/pilot-programs/evidence/{evidence['id']}/decision", headers=HEADERS, json={"decision": "VERIFIED", "reason": "test"})
        for role in req["required_roles"]:
            response = client.post(f"/v1/pilot-programs/{program['id']}/attestations", headers=HEADERS, json={"gate_key": gate, "role": role, "decision": "APPROVE", "notes": "test"})
            assert response.status_code == 201, response.text
    assert client.get(f"/v1/pilot-programs/{program['id']}/go-no-go", headers=HEADERS).json()["decision"] == "GO"
    return program


def _complete_onboarding(client, pilot_id):
    row = client.post("/v1/commercial/onboardings", headers=HEADERS, json={"name": "GA Customer Onboarding", "pilot_program_id": pilot_id}).json()
    requirements = client.get("/v1/commercial/onboarding-schema", headers=HEADERS).json()["requirements"]
    stages = ["CONFIGURATION", "SHADOW", "AGENT_DRAFT", "LIVE_SEND", "COMPLETED"]
    for stage in stages:
        updates = {key: True for key in requirements[stage]}
        client.patch(f"/v1/commercial/onboardings/{row['id']}/checklist", headers=HEADERS, json={"updates": updates})
        result = client.post(f"/v1/commercial/onboardings/{row['id']}/transition", headers=HEADERS, json={"target": stage})
        assert result.status_code == 200, result.text
    return row


def test_ga_release_requires_real_evidence_and_snapshot_bound_attestations(client):
    pilot = _pilot_go(client)
    client.post("/v1/commercial/subscriptions", headers=HEADERS, json={"plan_key": "starter", "billing_cycle": "monthly", "trial_days": 14, "provider": "manual"})
    _complete_onboarding(client, pilot["id"])
    # Publish required compliance documents and add legal review approvals (Gap 8).
    for key in ("terms", "privacy", "dpa", "subprocessors", "security_whitepaper"):
        response = client.post("/v1/compliance/documents", headers=HEADERS, json={"document_key": key, "title": key, "version": "1.0", "artifact_ref": f"file://{key}.md", "content_hash": (key[0] * 64)})
        assert response.status_code == 201, response.text
        doc_id = response.json()["id"]
        for reviewer_role in ("legal_owner", "privacy_owner"):
            legal = client.post(f"/v1/compliance/documents/{doc_id}/legal-review", headers=HEADERS, json={"reviewer_role": reviewer_role, "decision": "APPROVED", "jurisdiction": "CN", "notes": "test approval"})
            assert legal.status_code == 201, legal.text
    # Gap 7: External third-party penetration test with all remediations completed.
    pentest = client.post("/v1/commercial/pentest-reports", headers=HEADERS, json={"test_date": date.today().isoformat(), "tester_type": "EXTERNAL_THIRD_PARTY", "scope": "full production", "remediation_status": "ALL_REMEDIATED", "report_ref": "file://pentest.pdf"})
    assert pentest.status_code == 201, pentest.text
    ga = client.post("/v1/ga/programs", headers=HEADERS, json={"name": "Commercial GA Test", "pilot_program_id": pilot["id"], "targets": {"design_partners": 1}}).json()
    initial = client.get(f"/v1/ga/programs/{ga['id']}/go-no-go", headers=HEADERS).json()
    assert initial["decision"] == "NO_GO"
    schema = client.get("/v1/ga/schema", headers=HEADERS).json()["gates"]
    for gate, spec in schema.items():
        for evidence_type in spec["required_evidence"]:
            evidence = client.post(f"/v1/ga/programs/{ga['id']}/evidence", headers=HEADERS, json={"gate_key": gate, "evidence_type": evidence_type, "source": "test", "metrics": {"passed": True}}).json()
            verify = client.post(f"/v1/ga/evidence/{evidence['id']}/decision", headers=HEADERS, json={"decision": "VERIFIED", "reason": "checked"})
            assert verify.status_code == 200, verify.text
        for role in spec["required_roles"]:
            att = client.post(f"/v1/ga/programs/{ga['id']}/attestations", headers=HEADERS, json={"gate_key": gate, "role": role, "decision": "APPROVE", "notes": "approved"})
            assert att.status_code == 201, att.text
    # Gap 11: Start observation window, fast-forward window_end to past, then check to complete.
    ow = client.post(f"/v1/ga/programs/{ga['id']}/observation-window/start", headers=HEADERS, json={"days": 30})
    assert ow.status_code == 201, ow.text
    with client.app.state.SessionLocal() as session:
        window = session.scalar(select(ObservationWindow).where(ObservationWindow.ga_program_id == ga["id"], ObservationWindow.status == "OBSERVING"))
        assert window is not None
        window.window_end = utcnow() - timedelta(minutes=5)  # fast-forward for testing
        session.commit()
    checked = client.post(f"/v1/ga/programs/{ga['id']}/observation-window/check", headers=HEADERS)
    assert checked.status_code == 200, checked.text
    assert checked.json()["status"] == "COMPLETED"
    report = client.get(f"/v1/ga/programs/{ga['id']}/go-no-go", headers=HEADERS).json()
    assert report["decision"] == "GO", report
    extra = client.post(f"/v1/ga/programs/{ga['id']}/evidence", headers=HEADERS, json={"gate_key": "VALUE", "evidence_type": "time_saved", "source": "new-observation", "metrics": {"passed": True, "hours": 100}}).json()
    client.post(f"/v1/ga/evidence/{extra['id']}/decision", headers=HEADERS, json={"decision": "VERIFIED", "reason": "new data"})
    invalidated = client.get(f"/v1/ga/programs/{ga['id']}/gates/VALUE", headers=HEADERS).json()
    assert invalidated["ready"] is False
    assert invalidated["missing_attestations"]


def test_organization_invite_respects_subscription_and_role_updates(client):
    client.post("/v1/commercial/subscriptions", headers=HEADERS, json={"plan_key": "starter", "billing_cycle": "monthly", "trial_days": 14, "provider": "manual"})
    invited = client.post("/v1/organization/users", headers=HEADERS, json={"email": "member@example.com", "name": "Member", "role": "member"})
    assert invited.status_code == 201, invited.text
    changed = client.patch(f"/v1/organization/users/{invited.json()['id']}/role", headers=HEADERS, json={"role": "business_owner"})
    assert changed.status_code == 200
    org = client.get("/v1/organization", headers=HEADERS).json()
    assert any(x["email"] == "member@example.com" and x["role"] == "business_owner" for x in org["users"])


def test_pricing_approval_binds_catalog_hash_and_gates_activation(client):
    """Gap 1: Pricing approval binds to catalog hash and gates subscription activation."""
    client.get("/v1/commercial/plans", headers=HEADERS)  # ensure catalog exists
    # Without approval, activation should fail
    sub = client.post("/v1/commercial/subscriptions", headers=HEADERS, json={"plan_key": "starter", "billing_cycle": "monthly", "trial_days": 14, "provider": "manual"})
    assert sub.status_code == 201
    # Attempt to activate without pricing approval
    no_approval = client.post(f"/v1/commercial/subscriptions/{sub.json()['id']}/transition", headers=HEADERS, json={"target": "ACTIVE", "provider_ref": "contract-1"})
    assert no_approval.status_code == 422
    # Approve pricing with contract reference
    approval = client.post("/v1/commercial/pricing-approvals", headers=HEADERS, json={"approver_role": "finance_owner", "decision": "APPROVED", "contract_ref": "contract-WB-001", "notes": "formal approval"})
    assert approval.status_code == 201, approval.text
    assert approval.json()["decision"] == "APPROVED"
    assert approval.json()["contract_ref"] == "contract-WB-001"
    # Check status endpoint
    status = client.get("/v1/commercial/pricing-approvals/status", headers=HEADERS).json()
    assert status["approved"] is True
    # Now activation should succeed
    activated = client.post(f"/v1/commercial/subscriptions/{sub.json()['id']}/transition", headers=HEADERS, json={"target": "ACTIVE", "provider_ref": "contract-WB-001"})
    assert activated.status_code == 200
    assert activated.json()["status"] == "ACTIVE"


def test_model_agreement_dpa_and_cost_tracking(client):
    """Gap 5: Model provider agreement tracks DPA status and cost rates."""
    agreement = client.post("/v1/commercial/model-agreements", headers=HEADERS, json={
        "provider": "openai", "model_name": "gpt-5-mini", "dpa_status": "SIGNED",
        "dpa_ref": "dpa-2026-001", "processing_region": "CN",
        "input_cost_cny_fen_per_million": 5000, "output_cost_cny_fen_per_million": 15000,
    })
    assert agreement.status_code == 201, agreement.text
    assert agreement.json()["dpa_status"] == "SIGNED"
    assert agreement.json()["input_cost_cny_fen_per_million"] == 5000
    listed = client.get("/v1/commercial/model-agreements", headers=HEADERS).json()
    assert len(listed) >= 1
    assert any(a["provider"] == "openai" for a in listed)


def test_pentest_report_tracks_external_remediation(client):
    """Gap 7: Penetration test report tracks tester type and remediation status."""
    report = client.post("/v1/commercial/pentest-reports", headers=HEADERS, json={
        "test_date": date.today().isoformat(), "tester_type": "EXTERNAL_THIRD_PARTY",
        "scope": "production infrastructure", "remediation_status": "ALL_REMEDIATED",
        "report_ref": "file://pentest-2026.pdf", "findings": [{"id": "F01", "severity": "high", "status": "remediated"}],
    })
    assert report.status_code == 201, report.text
    assert report.json()["tester_type"] == "EXTERNAL_THIRD_PARTY"
    assert report.json()["remediation_status"] == "ALL_REMEDIATED"
    listed = client.get("/v1/commercial/pentest-reports", headers=HEADERS).json()
    assert any(r["tester_type"] == "EXTERNAL_THIRD_PARTY" for r in listed)


def test_legal_review_requires_both_roles(client):
    """Gap 8: Legal review requires both legal_owner and privacy_owner approval."""
    doc = client.post("/v1/compliance/documents", headers=HEADERS, json={"document_key": "terms", "title": "Terms", "version": "1.0", "artifact_ref": "file://terms.md", "content_hash": "a" * 64})
    assert doc.status_code == 201
    doc_id = doc.json()["id"]
    legal = client.post(f"/v1/compliance/documents/{doc_id}/legal-review", headers=HEADERS, json={"reviewer_role": "legal_owner", "decision": "APPROVED", "jurisdiction": "CN"})
    assert legal.status_code == 201
    privacy = client.post(f"/v1/compliance/documents/{doc_id}/legal-review", headers=HEADERS, json={"reviewer_role": "privacy_owner", "decision": "APPROVED", "jurisdiction": "CN"})
    assert privacy.status_code == 201
    reviews = client.get("/v1/compliance/legal-reviews", headers=HEADERS).json()
    assert len(reviews) >= 2
    roles = {r["reviewer_role"] for r in reviews if r["document_id"] == doc_id}
    assert roles == {"legal_owner", "privacy_owner"}


def test_oncall_schedule_and_coverage(client):
    """Gap 9: On-call schedule, shifts, and coverage verification."""
    schedule = client.post("/v1/oncall/schedules", headers=HEADERS, json={"name": "Primary Rotation", "timezone": "Asia/Shanghai"})
    assert schedule.status_code == 201, schedule.text
    sid = schedule.json()["id"]
    now = utcnow()
    shift = client.post(f"/v1/oncall/schedules/{sid}/shifts", headers=HEADERS, json={
        "responder_id": "oncall-1", "responder_contact": "pager://oncall-1",
        "role": "primary", "shift_start": now.isoformat(), "shift_end": (now + timedelta(hours=8)).isoformat(),
    })
    assert shift.status_code == 201, shift.text
    current = client.get("/v1/oncall/current", headers=HEADERS).json()
    assert len(current) >= 1
    assert current[0]["responder_id"] == "oncall-1"
    policy = client.post("/v1/oncall/escalation-policies", headers=HEADERS, json={
        "severity": "P0", "steps": [{"wait_minutes": 0, "notify": "primary-oncall"}, {"wait_minutes": 15, "notify": "engineering-manager"}],
    })
    assert policy.status_code == 201
    coverage = client.get("/v1/oncall/coverage", headers=HEADERS).json()
    assert "covered" in coverage


def test_observation_window_resets_on_p0_p1(client):
    """Gap 11: Observation window resets when P0/P1 incident occurs."""
    pilot = _pilot_go(client)
    client.post("/v1/commercial/subscriptions", headers=HEADERS, json={"plan_key": "starter", "billing_cycle": "monthly", "trial_days": 14, "provider": "manual"})
    _complete_onboarding(client, pilot["id"])
    for key in ("terms", "privacy", "dpa", "subprocessors", "security_whitepaper"):
        doc = client.post("/v1/compliance/documents", headers=HEADERS, json={"document_key": key, "title": key, "version": "1.0", "artifact_ref": f"file://{key}.md", "content_hash": (key[0] * 64)})
        for role in ("legal_owner", "privacy_owner"):
            client.post(f"/v1/compliance/documents/{doc.json()['id']}/legal-review", headers=HEADERS, json={"reviewer_role": role, "decision": "APPROVED"})
    client.post("/v1/commercial/pentest-reports", headers=HEADERS, json={"test_date": date.today().isoformat(), "tester_type": "EXTERNAL_THIRD_PARTY", "scope": "prod", "remediation_status": "ALL_REMEDIATED"})
    ga = client.post("/v1/ga/programs", headers=HEADERS, json={"name": "OW Reset Test", "pilot_program_id": pilot["id"]}).json()
    ow = client.post(f"/v1/ga/programs/{ga['id']}/observation-window/start", headers=HEADERS, json={"days": 30})
    assert ow.status_code == 201
    assert ow.json()["status"] == "OBSERVING"
    assert ow.json()["reset_count"] == 0
    # Create a P1 support ticket to trigger reset
    client.post("/v1/support/tickets", headers=HEADERS, json={"severity": "P1", "category": "incident", "title": "P1 during observation", "description": "test"})
    # Check observation window - should reset
    checked = client.post(f"/v1/ga/programs/{ga['id']}/observation-window/check", headers=HEADERS)
    assert checked.status_code == 200
    assert checked.json()["reset_count"] >= 1
    assert checked.json()["status"] == "OBSERVING"


def test_billing_webhook_idempotency(client):
    """Gap 2: Billing webhook processes payment idempotently."""
    client.post("/v1/commercial/subscriptions", headers=HEADERS, json={"plan_key": "starter", "billing_cycle": "monthly", "trial_days": 0, "provider": "manual"})
    sub = client.get("/v1/commercial/subscription", headers=HEADERS).json()
    invoice = client.post("/v1/commercial/invoices", headers=HEADERS, json={"subscription_id": sub["id"], "tax_rate_basis_points": 0})
    assert invoice.status_code == 201
    inv_id = invoice.json()["id"]
    client.post(f"/v1/commercial/invoices/{inv_id}/transition", headers=HEADERS, json={"target": "OPEN"})
    inv_number = invoice.json()["invoice_number"]
    # Send webhook
    webhook1 = client.post("/v1/commercial/billing/webhook", json={"invoice_ref": inv_number, "event_type": "payment.succeeded"}, headers={"X-Webhook-Signature": "test-signature"})
    assert webhook1.status_code == 200
    assert webhook1.json()["verified"] is True
    # Replay webhook - should be idempotent
    webhook2 = client.post("/v1/commercial/billing/webhook", json={"invoice_ref": inv_number, "event_type": "payment.succeeded"}, headers={"X-Webhook-Signature": "test-signature"})
    assert webhook2.status_code == 200
    # Invoice should be PAID
    invoices = client.get("/v1/commercial/invoices", headers=HEADERS).json()
    paid = [i for i in invoices if i["id"] == inv_id][0]
    assert paid["status"] == "PAID"


def test_design_partner_profile_update(client):
    """Gap 10: Design partner profile can be updated on onboarding records."""
    onboarding = client.post("/v1/commercial/onboardings", headers=HEADERS, json={"name": "Partner Profile Test"}).json()
    profile = client.patch(f"/v1/commercial/onboardings/{onboarding['id']}/design-partner-profile", headers=HEADERS, json={
        "profile": {"company": "Acme Corp", "industry": "SaaS", "team_size": 50, "use_case": "customer success automation"},
    })
    assert profile.status_code == 200, profile.text
    assert profile.json()["design_partner_profile"]["company"] == "Acme Corp"
    assert profile.json()["design_partner_profile"]["industry"] == "SaaS"


def test_ga_attestation_has_cryptographic_signature(client):
    """Gap 12: GA attestations include cryptographic signatures."""
    from workbuddy.services.gate_signing import verify_attestation_signature
    pilot = _pilot_go(client)
    client.post("/v1/commercial/subscriptions", headers=HEADERS, json={"plan_key": "starter", "billing_cycle": "monthly", "trial_days": 14, "provider": "manual"})
    _complete_onboarding(client, pilot["id"])
    for key in ("terms", "privacy", "dpa", "subprocessors", "security_whitepaper"):
        doc = client.post("/v1/compliance/documents", headers=HEADERS, json={"document_key": key, "title": key, "version": "1.0", "artifact_ref": f"file://{key}.md", "content_hash": (key[0] * 64)})
        for role in ("legal_owner", "privacy_owner"):
            client.post(f"/v1/compliance/documents/{doc.json()['id']}/legal-review", headers=HEADERS, json={"reviewer_role": role, "decision": "APPROVED"})
    client.post("/v1/commercial/pentest-reports", headers=HEADERS, json={"test_date": date.today().isoformat(), "tester_type": "EXTERNAL_THIRD_PARTY", "scope": "prod", "remediation_status": "ALL_REMEDIATED"})
    ga = client.post("/v1/ga/programs", headers=HEADERS, json={"name": "Sig Test", "pilot_program_id": pilot["id"]}).json()
    # Submit and verify one piece of evidence
    evidence = client.post(f"/v1/ga/programs/{ga['id']}/evidence", headers=HEADERS, json={"gate_key": "GA", "evidence_type": "production_open_go", "source": "test", "metrics": {"passed": True}}).json()
    client.post(f"/v1/ga/evidence/{evidence['id']}/decision", headers=HEADERS, json={"decision": "VERIFIED"})
    # Attest with a role
    att = client.post(f"/v1/ga/programs/{ga['id']}/attestations", headers=HEADERS, json={"gate_key": "GA", "role": "product_owner", "decision": "APPROVE", "notes": "signed"})
    assert att.status_code == 201, att.text
    assert att.json()["cryptographic_signature"]
    assert att.json()["signing_key_id"].startswith("hmac-sha256:")
    # Verify the signature cryptographically
    valid = verify_attestation_signature(
        role="product_owner", decision="APPROVE",
        snapshot_hash=att.json()["evidence_snapshot_hash"], actor_id="owner",
        timestamp=att.json()["signed_at"], signature=att.json()["cryptographic_signature"],
    )
    assert valid is True
