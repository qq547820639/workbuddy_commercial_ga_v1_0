from __future__ import annotations

from sqlalchemy import select

from workbuddy.db.models import MailAccount, ModelInvocation, OperationAttempt, SkillDefinition, SkillRelease
from workbuddy.services.external_actions import prepare_external_operation
from workbuddy.services.policies import PolicyViolation
from workbuddy.settings import Settings

TENANT = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Tenant-ID": TENANT, "X-Actor-ID": "owner"}


def _create_running_mission(client):
    client.post("/v1/demo/bootstrap", headers=HEADERS)
    sales = next(x for x in client.get("/v1/inbox", headers=HEADERS).json() if x["provider_message_id"] == "demo:sales:1")
    mission = client.post(f"/v1/dispatch/{sales['dispatch']['id']}/confirm", headers=HEADERS, json={"team_key": "sales_growth"}).json()
    for path, reason in [("accept", "接单"), ("plan", "规划"), ("approve-plan", "批准计划"), ("start", "启动")]:
        mission = client.post(f"/v1/missions/{mission['id']}/{path}", headers=HEADERS, json={"expected_version": mission["version"], "reason": reason}).json()
    return mission


def _complete_mission_for_approval(client):
    mission = _create_running_mission(client)
    for _ in range(12):
        detail = client.get(f"/v1/missions/{mission['id']}", headers=HEADERS).json()
        if all(x["status"] == "ACCEPTED" for x in detail["work_items"]):
            break
        startable = next((x for x in detail["work_items"] if x["status"] in {"READY", "ASSIGNED", "REVISION_REQUIRED"}), None)
        if startable:
            run = client.post(f"/v1/work-items/{startable['id']}/start", headers=HEADERS).json()
            executed = client.post(f"/v1/agent-runs/{run['id']}/execute", headers=HEADERS, json={"force_provider": "configured"})
            assert executed.status_code == 200, executed.text
        submitted = next((x for x in client.get(f"/v1/missions/{mission['id']}", headers=HEADERS).json()["work_items"] if x["status"] == "SUBMITTED"), None)
        if submitted:
            reviewed = client.post(f"/v1/work-items/{submitted['id']}/review", headers=HEADERS, json={"decision": "accept", "reason": "质量门通过"})
            assert reviewed.status_code == 200, reviewed.text
    detail = client.get(f"/v1/missions/{mission['id']}", headers=HEADERS).json()
    current = detail["mission"]
    reviewed = client.post(f"/v1/missions/{mission['id']}/lead-review", headers=HEADERS, json={"expected_version": current["version"], "reason": "主理人整合"}).json()
    return reviewed["mission"], reviewed["approval"]


def test_agent_execution_records_model_and_quality(client):
    mission = _create_running_mission(client)
    detail = client.get(f"/v1/missions/{mission['id']}", headers=HEADERS).json()
    item = next(x for x in detail["work_items"] if x["status"] in {"READY", "ASSIGNED"})
    run = client.post(f"/v1/work-items/{item['id']}/start", headers=HEADERS).json()
    result = client.post(f"/v1/agent-runs/{run['id']}/execute", headers=HEADERS, json={"force_provider": "configured"})
    assert result.status_code == 200
    assert result.json()["status"] == "CLOSED"
    invocations = client.get("/v1/model/invocations?task_type=agent_execute", headers=HEADERS).json()
    assert invocations and invocations[0]["status"] == "SUCCEEDED"
    reviewed = client.post(f"/v1/work-items/{item['id']}/review", headers=HEADERS, json={"decision": "accept", "reason": "符合标准"})
    assert reviewed.status_code == 200
    quality = client.get("/v1/quality", headers=HEADERS).json()
    assert quality["evaluations"] >= 1
    assert quality["pass_rate"] == 100.0


def test_dispatch_shadow_metrics_and_feedback(client):
    client.post("/v1/demo/bootstrap", headers=HEADERS)
    inbox = client.get("/v1/inbox", headers=HEADERS).json()
    decision = inbox[0]["dispatch"]
    response = client.post(f"/v1/dispatch/{decision['id']}/feedback", headers=HEADERS, json={
        "confirmed_team_key": "customer_success", "corrected_risk_level": "high", "comment": "试点纠正"
    })
    assert response.status_code == 200
    metrics = client.get("/v1/pilot/dispatch-metrics", headers=HEADERS).json()
    assert metrics["shadow_mode"] is True
    assert metrics["reviewed"] >= 1


def test_skill_requires_test_before_publish_but_publish_runs_tests(client):
    content = b'''skill_key: beta-user-skill\nsemantic_version: 1.0.0\nname: Beta User Skill\ninputs: [mission_context]\noutputs: [structured_artifact]\ntools: []\npermissions:\n  data_scope: current_mission\n  external_write: false\nquality_gates: [facts need sources]\n'''
    uploaded = client.post("/v1/skills/upload", headers=HEADERS, files={"file": ("skill.yaml", content, "text/yaml")})
    assert uploaded.status_code == 201
    release = uploaded.json()
    tested = client.post(f"/v1/skills/{release['id']}/test", headers=HEADERS, json={"test_input": {"sample": True}})
    assert tested.status_code == 200
    assert tested.json()["status"] == "approved"
    published = client.post(f"/v1/skills/{release['id']}/publish", headers=HEADERS)
    assert published.status_code == 200
    assert published.json()["status"] == "published"


def test_demo_operation_records_attempt_and_readiness(client):
    mission, approval = _complete_mission_for_approval(client)
    client.post(f"/v1/approvals/{approval['id']}/decision", headers=HEADERS, json={"decision": "approve", "reason": "批准"})
    operation = client.post("/v1/operations", headers=HEADERS, json={"approval_id": approval["id"], "operation_key": "beta-demo-1"}).json()
    assert operation["demo_mode"] is True
    executed = client.post(f"/v1/operations/{operation['id']}/execute", headers=HEADERS, json={"simulate_unknown": False}).json()
    assert executed["status"] == "SUCCEEDED"
    attempts = client.get(f"/v1/operations/{operation['id']}/attempts", headers=HEADERS).json()
    assert len(attempts) == 1 and attempts[0]["status"] == "SUCCEEDED"
    readiness = client.get("/v1/beta/readiness", headers=HEADERS).json()
    assert readiness["checks"]["model_invocations_observed"] is True


def test_live_prepare_enforces_recipient_allowlist(client):
    _mission, approval = _complete_mission_for_approval(client)
    client.post(f"/v1/approvals/{approval['id']}/decision", headers=HEADERS, json={"decision": "approve", "reason": "批准"})
    with client.app.state.SessionLocal() as session:
        account = MailAccount(tenant_id=TENANT, provider="gmail", address="owner@example.com", status="active", send_enabled=True, scopes=["https://www.googleapis.com/auth/gmail.send"])
        session.add(account); session.flush()
        from workbuddy.db.models import ApprovalRequest
        row = session.get(ApprovalRequest, approval["id"])
        row.exact_action = {**row.exact_action, "account_id": account.id, "to": ["sarah@techbridge.io"]}
        from workbuddy.services.common import content_hash
        row.content_hash = content_hash(row.exact_action)
        session.commit()
        cfg = Settings(enable_live_email_send=True, allowed_recipient_domains=("example.com",))
        try:
            prepare_external_operation(session, TENANT, approval["id"], "live-blocked-1", cfg)
        except PolicyViolation as exc:
            assert "allowlist" in str(exc)
        else:
            raise AssertionError("recipient outside allowlist should be blocked")


def test_live_gmail_path_uses_exact_approval_and_provider_verification(client):
    _mission, approval = _complete_mission_for_approval(client)
    client.post(f"/v1/approvals/{approval['id']}/decision", headers=HEADERS, json={"decision": "approve", "reason": "批准"})

    class FakeGmail:
        def valid_access_token(self, _session, _account):
            return "task-scoped-token"

        def send_message(self, token, action):
            assert token == "task-scoped-token"
            assert action["to"] == ["sarah@techbridge.io"]
            return {"id": "gmail-provider-message-1", "threadId": "gmail-thread-1"}

        def verify_sent(self, token, provider_id):
            assert token == "task-scoped-token"
            return {"verified": provider_id == "gmail-provider-message-1", "id": provider_id}

    with client.app.state.SessionLocal() as session:
        from workbuddy.db.models import ApprovalRequest, TenantPolicy
        from workbuddy.services.common import content_hash
        from workbuddy.services.external_actions import execute_external_operation

        account = MailAccount(
            tenant_id=TENANT,
            provider="gmail",
            address="owner@example.com",
            status="active",
            send_enabled=True,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        session.add(account)
        session.flush()
        row = session.get(ApprovalRequest, approval["id"])
        row.exact_action = {
            **row.exact_action,
            "account_id": account.id,
            "to": ["sarah@techbridge.io"],
            "cc": [],
            "bcc": [],
            "attachments": [],
        }
        row.content_hash = content_hash(row.exact_action)
        policy = session.scalar(select(TenantPolicy).where(TenantPolicy.tenant_id == TENANT, TenantPolicy.policy_key == "external_email"))
        policy.config = {
            **policy.config,
            "allowed_recipient_domains": ["techbridge.io"],
            "allowed_recipient_addresses": [],
        }
        cfg = Settings(
            enable_live_email_send=True,
            allowed_recipient_domains=("techbridge.io",),
            daily_send_limit=2,
            mission_send_limit=1,
        )
        op = prepare_external_operation(session, TENANT, approval["id"], "live-success-1", cfg)
        assert op.demo_mode is False
        finished = execute_external_operation(session, TENANT, op.id, gmail=FakeGmail(), cfg=cfg)
        session.commit()
        assert finished.status == "SUCCEEDED"
        assert finished.provider_reference == "gmail-provider-message-1"
        assert finished.provider_result["verification"]["verified"] is True


def test_graph_subscription_validation_webhook_dedup_and_tenant_mapping(client, monkeypatch):
    from datetime import datetime, timedelta, timezone
    from workbuddy.api import beta_routes

    class FakeGraph:
        def valid_access_token(self, _session, _account):
            return "graph-token"

        def create_subscription(self, token, notification_url, client_state, resource="me/mailFolders('inbox')/messages"):
            assert token == "graph-token"
            assert notification_url.endswith("/v1/connectors/graph/webhook")
            return {
                "id": "graph-sub-1",
                "resource": resource,
                "expirationDateTime": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat().replace("+00:00", "Z"),
            }

        def renew_subscription(self, token, subscription_id):
            raise AssertionError("first watch should create, not renew")

    monkeypatch.setattr(beta_routes, "graph", FakeGraph())
    with client.app.state.SessionLocal() as session:
        account = MailAccount(
            tenant_id=TENANT,
            provider="graph",
            address="owner@example.com",
            status="active",
            encrypted_credentials="fake",
        )
        session.add(account)
        session.commit()
        account_id = account.id

    validation = client.get("/v1/connectors/graph/webhook?validationToken=verify-me")
    assert validation.status_code == 200 and validation.text == "verify-me"

    watched = client.post(f"/v1/connectors/graph/accounts/{account_id}/watch", headers=HEADERS)
    assert watched.status_code == 200, watched.text
    assert watched.json()["subscription_id"] == "graph-sub-1"

    with client.app.state.SessionLocal() as session:
        account = session.get(MailAccount, account_id)
        client_state = account.subscription_client_state

    wrong_state = {"value": [{
        "subscriptionId": "graph-sub-1",
        "sequenceNumber": "0",
        "resource": "me/mailFolders('inbox')/messages/malicious",
        "clientState": "incorrect-client-state",
        "changeType": "created",
    }]}
    rejected = client.post("/v1/connectors/graph/webhook", json=wrong_state)
    assert rejected.status_code == 200
    assert rejected.json()["rejected"] == 1

    payload = {"value": [{
        "subscriptionId": "graph-sub-1",
        "sequenceNumber": "1",
        "resource": "me/mailFolders('inbox')/messages/message-1",
        "clientState": client_state,
        "changeType": "created",
    }]}
    first = client.post("/v1/connectors/graph/webhook", json=payload)
    second = client.post("/v1/connectors/graph/webhook", json=payload)
    assert first.json()["accepted"] == 1
    assert second.json()["duplicates"] == 1
    with client.app.state.SessionLocal() as session:
        assert session.get(MailAccount, account_id).sync_status == "pending"


def test_gmail_webhook_binding_routes_without_tenant_header_and_deduplicates(client):
    import base64
    import json
    from workbuddy.db.models import WebhookBinding

    address = "webhook-owner@example.com"
    with client.app.state.SessionLocal() as session:
        account = MailAccount(
            tenant_id=TENANT,
            provider="gmail",
            address=address,
            status="active",
            encrypted_credentials="unused-because-cursor-is-initialized-only",
            cursor=None,
        )
        session.add(account)
        session.flush()
        session.add(WebhookBinding(
            provider="gmail",
            external_key=address,
            tenant_id=TENANT,
            account_id=account.id,
        ))
        session.commit()
        account_id = account.id

    notice = {"emailAddress": address, "historyId": "12345"}
    payload = {
        "message": {
            "messageId": "gmail-pubsub-event-1",
            "data": base64.b64encode(json.dumps(notice).encode()).decode(),
        }
    }
    first = client.post("/v1/connectors/gmail/webhook", json=payload)
    second = client.post("/v1/connectors/gmail/webhook", json=payload)
    assert first.status_code == 200, first.text
    assert first.json()["initialized_cursor"] == "12345"
    assert second.status_code == 200, second.text
    assert second.json()["duplicate"] is True
    with client.app.state.SessionLocal() as session:
        assert session.get(MailAccount, account_id).cursor == "12345"


def test_gmail_provider_verification_requires_sent_label(monkeypatch):
    from workbuddy.connectors.gmail import GmailConnector

    connector = GmailConnector()
    monkeypatch.setattr(connector, "get_message", lambda _token, _id: {
        "id": "message-1", "threadId": "thread-1", "labelIds": ["INBOX"]
    })
    result = connector.verify_sent("token", "message-1")
    assert result["verified"] is False
    assert result["sent_label"] is False

    monkeypatch.setattr(connector, "get_message", lambda _token, _id: {
        "id": "message-1", "threadId": "thread-1", "labelIds": ["SENT"]
    })
    result = connector.verify_sent("token", "message-1")
    assert result["verified"] is True
    assert result["sent_label"] is True


def test_live_transport_error_is_persisted_as_unknown_not_retried(client):
    import httpx
    from workbuddy.db.models import ApprovalRequest, TenantPolicy
    from workbuddy.services.common import content_hash
    from workbuddy.services.external_actions import execute_external_operation

    _mission, approval = _complete_mission_for_approval(client)
    client.post(f"/v1/approvals/{approval['id']}/decision", headers=HEADERS, json={"decision": "approve", "reason": "批准"})

    class TimeoutGmail:
        def valid_access_token(self, _session, _account):
            return "task-scoped-token"

        def send_message(self, _token, _action):
            request = httpx.Request("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
            raise httpx.ReadTimeout("provider response timed out", request=request)

    with client.app.state.SessionLocal() as session:
        account = MailAccount(
            tenant_id=TENANT,
            provider="gmail",
            address="owner@example.com",
            status="active",
            send_enabled=True,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        session.add(account)
        session.flush()
        row = session.get(ApprovalRequest, approval["id"])
        row.exact_action = {
            **row.exact_action,
            "account_id": account.id,
            "to": ["sarah@techbridge.io"],
            "cc": [], "bcc": [], "attachments": [],
        }
        row.content_hash = content_hash(row.exact_action)
        policy = session.scalar(select(TenantPolicy).where(
            TenantPolicy.tenant_id == TENANT, TenantPolicy.policy_key == "external_email"
        ))
        policy.config = {**policy.config, "allowed_recipient_domains": ["techbridge.io"]}
        cfg = Settings(
            enable_live_email_send=True,
            allowed_recipient_domains=("techbridge.io",),
            daily_send_limit=2,
            mission_send_limit=1,
        )
        op = prepare_external_operation(session, TENANT, approval["id"], "live-timeout-1", cfg)
        result = execute_external_operation(session, TENANT, op.id, gmail=TimeoutGmail(), cfg=cfg)
        session.commit()
        assert result.status == "UNKNOWN"
        assert result.error_code == "PROVIDER_TRANSPORT_ERROR"
        attempt = session.scalar(select(OperationAttempt).where(OperationAttempt.operation_id == op.id))
        assert attempt.status == "UNKNOWN"
        try:
            execute_external_operation(session, TENANT, op.id, gmail=TimeoutGmail(), cfg=cfg)
        except Exception as exc:
            assert "must be verified" in str(exc)
        else:
            raise AssertionError("UNKNOWN operation must not be retried directly")


def test_graph_webhook_batch_routes_multiple_tenants(client):
    from workbuddy.db.models import Tenant, WebhookBinding
    from workbuddy.services.common import content_hash

    second_tenant = "00000000-0000-0000-0000-000000000002"
    with client.app.state.SessionLocal() as session:
        session.add(Tenant(id=second_tenant, name="Second tenant", status="active"))
        session.flush()
        first = MailAccount(
            tenant_id=TENANT, provider="graph", address="first@example.com", status="active",
            encrypted_credentials="fake", provider_subscription_id="multi-sub-1", subscription_client_state="state-1",
        )
        second = MailAccount(
            tenant_id=second_tenant, provider="graph", address="second@example.com", status="active",
            encrypted_credentials="fake", provider_subscription_id="multi-sub-2", subscription_client_state="state-2",
        )
        session.add_all([first, second]); session.flush()
        session.add_all([
            WebhookBinding(provider="graph", external_key="multi-sub-1", tenant_id=TENANT, account_id=first.id, verification_hash=content_hash("state-1")),
            WebhookBinding(provider="graph", external_key="multi-sub-2", tenant_id=second_tenant, account_id=second.id, verification_hash=content_hash("state-2")),
        ])
        session.commit()
        first_id, second_id = first.id, second.id

    payload = {"value": [
        {"subscriptionId": "multi-sub-1", "sequenceNumber": "1", "resource": "messages/a", "clientState": "state-1", "changeType": "created"},
        {"subscriptionId": "multi-sub-2", "sequenceNumber": "1", "resource": "messages/b", "clientState": "state-2", "changeType": "created"},
    ]}
    response = client.post("/v1/connectors/graph/webhook", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["accepted"] == 2
    with client.app.state.SessionLocal() as session:
        assert session.get(MailAccount, first_id).sync_status == "pending"
        assert session.get(MailAccount, second_id).sync_status == "pending"


def test_model_gateway_rejects_schema_type_and_additional_property_violations():
    from workbuddy.services.model_gateway import ModelGateway, ModelGatewayError

    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"count": {"type": "integer"}},
        "required": ["count"],
    }
    for invalid in ({"count": "1"}, {"count": 1, "unexpected": True}):
        try:
            ModelGateway._validate_schema(invalid, schema)
        except ModelGatewayError as exc:
            assert "schema validation" in str(exc)
        else:
            raise AssertionError("invalid structured model output must be rejected")


def test_agent_model_failure_is_persisted_and_work_item_is_blocked(client):
    from workbuddy.db.models import ModelInvocation, ToolGrant, WorkItem
    from workbuddy.services.executor import execute_agent_run
    from workbuddy.services.model_gateway import ModelGateway

    mission = _create_running_mission(client)
    detail = client.get(f"/v1/missions/{mission['id']}", headers=HEADERS).json()
    item = next(x for x in detail["work_items"] if x["status"] in {"READY", "ASSIGNED"})
    run = client.post(f"/v1/work-items/{item['id']}/start", headers=HEADERS).json()
    with client.app.state.SessionLocal() as session:
        failed = execute_agent_run(session, TENANT, run["id"], gateway=ModelGateway(Settings(model_provider="unsupported")))
        session.commit()
        assert failed.status == "CLOSED"
        assert failed.context_cleared is True
        assert failed.close_reason.startswith("failed:")
        assert session.get(WorkItem, item["id"]).status == "BLOCKED"
        invocation = session.scalar(select(ModelInvocation).where(ModelInvocation.agent_run_id == run["id"]))
        assert invocation.status == "FAILED"
        grants = session.scalars(select(ToolGrant).where(ToolGrant.agent_run_id == run["id"])).all()
        assert grants and all(g.active is False for g in grants)

    # A retry is explicit and creates a new task-scoped AgentRun; the failed Run is not reused.
    retry = client.post(f"/v1/work-items/{item['id']}/start", headers=HEADERS)
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] != run["id"]
    succeeded = client.post(f"/v1/agent-runs/{retry.json()['id']}/execute", headers=HEADERS, json={"force_provider": "configured"})
    assert succeeded.status_code == 200, succeeded.text


def test_graph_read_only_token_refresh_does_not_request_send_scope(monkeypatch):
    from workbuddy.connectors.microsoft_graph import MicrosoftGraphConnector, READ_SCOPES

    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"access_token": "refreshed", "expires_in": 3600, "scope": READ_SCOPES}

    def fake_post(_url, data, timeout):
        captured.update(data)
        return Response()

    monkeypatch.setattr("workbuddy.connectors.microsoft_graph.httpx.post", fake_post)
    connector = MicrosoftGraphConnector(Settings(graph_client_id="id", graph_client_secret="secret"))
    refreshed = connector.refresh({"refresh_token": "r", "scope": READ_SCOPES})
    assert "Mail.Send" not in captured["scope"]
    assert refreshed["refresh_token"] == "r"


def test_mail_upsert_updates_provider_state_and_revives_soft_deleted_message(client):
    from workbuddy.services.mission_service import ingest_mail

    with client.app.state.SessionLocal() as session:
        message = ingest_mail(session, TENANT, {
            "provider_message_id": "gmail:update-1",
            "sender": "A <a@example.com>",
            "recipients": ["owner@example.com"],
            "subject": "Old subject",
            "body_text": "Old body",
            "labels": ["INBOX"],
            "direction": "inbound",
        })
        session.commit()
        message.provider_deleted = True
        message.processing_status = "PROVIDER_DELETED"
        session.commit()
        updated = ingest_mail(session, TENANT, {
            "provider_message_id": "gmail:update-1",
            "sender": "A <a@example.com>",
            "recipients": ["owner@example.com"],
            "subject": "Updated subject",
            "body_text": "Updated body",
            "labels": ["SENT"],
            "direction": "outbound",
            "has_attachments": True,
        }, actor="test-sync")
        session.commit()
        assert updated.id == message.id
        assert updated.subject == "Updated subject"
        assert updated.labels == ["SENT"]
        assert updated.direction == "outbound"
        assert updated.provider_deleted is False
        assert updated.has_attachments is True


def test_inbox_hides_provider_deleted_messages(client):
    from workbuddy.services.mission_service import ingest_mail

    with client.app.state.SessionLocal() as session:
        message = ingest_mail(session, TENANT, {
            "provider_message_id": "graph:hidden-1",
            "sender": "A <a@example.com>",
            "recipients": ["owner@example.com"],
            "subject": "Deleted at provider",
            "body_text": "No longer active",
        })
        message.provider_deleted = True
        message.processing_status = "PROVIDER_DELETED"
        session.commit()
    inbox = client.get("/v1/inbox", headers=HEADERS).json()
    assert all(x["provider_message_id"] != "graph:hidden-1" for x in inbox)


def test_graph_delta_soft_marks_provider_deletion(client):
    from workbuddy.services.mission_service import ingest_mail
    from workbuddy.services.mail_sync import sync_graph_folder

    class FakeGraphDelta:
        def valid_access_token(self, _session, _account):
            return "token"

        def delta(self, _token, folder_id="inbox", cursor_url=None):
            return {
                "value": [{"id": "deleted-message", "@removed": {"reason": "deleted"}}],
                "@odata.deltaLink": "https://graph.example/delta/final",
            }

    with client.app.state.SessionLocal() as session:
        account = MailAccount(tenant_id=TENANT, provider="graph", address="owner@example.com", status="active", encrypted_credentials="fake")
        session.add(account); session.flush()
        message = ingest_mail(session, TENANT, {
            "provider_message_id": "graph:deleted-message",
            "sender": "A <a@example.com>", "recipients": ["owner@example.com"],
            "subject": "Will be deleted", "body_text": "body",
        })
        message.account_id = account.id
        session.commit()
        run = sync_graph_folder(session, TENANT, account, connector=FakeGraphDelta())
        session.commit()
        assert run.status == "SUCCEEDED"
        assert run.deleted_count == 1
        assert session.get(type(message), message.id).provider_deleted is True


def test_gmail_history_changes_collects_labels_and_deletions(monkeypatch):
    from workbuddy.connectors.gmail import GmailConnector

    connector = GmailConnector()
    pages = [{
        "historyId": "20",
        "history": [{
            "messagesAdded": [{"message": {"id": "a"}}],
            "labelsAdded": [{"message": {"id": "b"}, "labelIds": ["STARRED"]}],
            "labelsRemoved": [{"message": {"id": "c"}, "labelIds": ["INBOX"]}],
            "messagesDeleted": [{"message": {"id": "d"}}],
        }],
    }]
    monkeypatch.setattr(connector, "_get", lambda *_args, **_kwargs: pages.pop(0))
    changes, cursor = connector.history_changes("token", "10")
    assert cursor == "20"
    assert changes["upsert_ids"] == ["a", "b", "c"]
    assert changes["deleted_ids"] == ["d"]
