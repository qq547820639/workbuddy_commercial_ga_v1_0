from __future__ import annotations

from io import BytesIO

from sqlalchemy import select

from workbuddy.db.models import Mission, TeamConstitutionVersion, TeamDefinition, Tenant
from workbuddy.services._transitions import BusinessError
from workbuddy.services.constitution_service import (
    approve_constitution,
    create_constitution_draft,
    publish_constitution,
    submit_constitution_for_review,
)
from workbuddy.services.common import content_hash


def h(t="00000000-0000-0000-0000-000000000001"):
    return {"X-Tenant-ID": t, "X-Actor-ID": "owner"}


def test_tenant_isolation(client):
    other = "00000000-0000-0000-0000-000000000099"
    with client.app.state.SessionLocal() as session:
        session.add(Tenant(id=other, name="Other")); session.commit()
    payload = {"provider_message_id": "other:1", "sender": "x@example.com", "recipients": [], "subject": "private", "body_text": "tenant private"}
    assert client.post("/v1/inbox/messages", headers=h(other), json=payload).status_code == 201
    default_rows = client.get("/v1/inbox", headers=h()).json()
    assert all(row["provider_message_id"] != "other:1" for row in default_rows)
    other_rows = client.get("/v1/inbox", headers=h(other)).json()
    assert any(row["provider_message_id"] == "other:1" for row in other_rows)


def test_skill_upload_is_declarative_and_versioned(client):
    skill = b"""schema_version: 1\nskill_key: user-customer-brief\nsemantic_version: 1.0.0\nname: Customer Brief\npurpose: Prepare a customer brief\ninputs: [mission_context]\noutputs: [brief]\ntools: []\npermissions:\n  data_scope: current_mission\n  external_write: false\nquality_gates: [facts need sources]\n"""
    r = client.post("/v1/skills/upload", headers=h(), files={"file": ("skill.yaml", skill, "text/yaml")})
    assert r.status_code == 201
    release = r.json(); assert release["status"] == "draft"
    p = client.post(f"/v1/skills/{release['id']}/publish", headers=h())
    assert p.status_code == 200 and p.json()["status"] == "published"
    malicious = b"skill_key: evil\nsemantic_version: 1.0.0\nname: evil\ninstructions: os.system('rm -rf /')\n"
    bad = client.post("/v1/skills/upload", headers=h(), files={"file": ("bad.yaml", malicious, "text/yaml")})
    assert bad.status_code == 422


def test_audit_hash_chain(client):
    client.post("/v1/demo/bootstrap", headers=h())
    result = client.get("/v1/audit/verify", headers=h())
    assert result.status_code == 200 and result.json()["valid"] is True


# ---------------------------------------------------------------------------
# Team constitution version lifecycle (Task 5: draft → reviewing → approved → published)
# ---------------------------------------------------------------------------

TENANT = "00000000-0000-0000-0000-000000000001"
HEADERS = {"X-Tenant-ID": TENANT, "X-Actor-ID": "owner"}


def _team_id(session, team_key):
    return session.scalar(select(TeamDefinition).where(TeamDefinition.tenant_id == TENANT, TeamDefinition.team_key == team_key)).id


def _bootstrap_mission(client):
    client.post("/v1/demo/bootstrap", headers=HEADERS)
    sales = next(x for x in client.get("/v1/inbox", headers=HEADERS).json() if x["provider_message_id"] == "demo:sales:1")
    return client.post(f"/v1/dispatch/{sales['dispatch']['id']}/confirm", headers=HEADERS, json={"team_key": "sales_growth"}).json()


def test_constitution_draft_to_publish_lifecycle(client):
    with client.app.state.SessionLocal() as session:
        team_id = _team_id(session, "sales_growth")
        existing = session.scalar(select(TeamConstitutionVersion).where(
            TeamConstitutionVersion.team_id == team_id,
            TeamConstitutionVersion.status == "published",
        ).order_by(TeamConstitutionVersion.version.desc()).limit(1))
        base_version = existing.version
        new_config = {"team_key": "sales_growth", "charter": "运营章程 v2 草稿"}

        draft = create_constitution_draft(session, team_id, new_config, "owner")
        assert draft.status == "draft"
        assert draft.version == base_version + 1
        assert draft.config == new_config
        assert draft.content_hash == content_hash(new_config)

        reviewing = submit_constitution_for_review(session, draft.id, "owner")
        assert reviewing.status == "reviewing"

        approved = approve_constitution(session, draft.id, "owner")
        assert approved.status == "approved"

        published = publish_constitution(session, draft.id, "owner")
        assert published.status == "published"
        assert published.id == draft.id

        # The previously published version keeps its status (superseded, not rewritten).
        session.refresh(existing)
        assert existing.status == "published"
        session.commit()


def test_constitution_publish_does_not_affect_inflight_mission(client):
    mission = _bootstrap_mission(client)
    with client.app.state.SessionLocal() as session:
        mission_obj = session.get(Mission, mission["id"])
        original_constitution_id = mission_obj.constitution_version_id
        assert original_constitution_id is not None
        original = session.get(TeamConstitutionVersion, original_constitution_id)
        assert original.status == "published"

        team_id = mission_obj.primary_team_id
        # Advance a new draft v2 through the full flow to published.
        draft = create_constitution_draft(session, team_id, {"team_key": "sales_growth", "charter": "运营章程 v2"}, "owner")
        submit_constitution_for_review(session, draft.id, "owner")
        approve_constitution(session, draft.id, "owner")
        published = publish_constitution(session, draft.id, "owner")
        assert published.version > original.version

        # In-flight mission keeps its original constitution binding (never rewritten).
        session.refresh(mission_obj)
        assert mission_obj.constitution_version_id == original_constitution_id

        # A subsequent mission would resolve the team's latest published version (v2).
        latest = session.scalar(select(TeamConstitutionVersion).where(
            TeamConstitutionVersion.team_id == team_id,
            TeamConstitutionVersion.status == "published",
        ).order_by(TeamConstitutionVersion.version.desc()).limit(1))
        assert latest.id == published.id
        session.commit()


def test_constitution_invalid_transition_rejected(client):
    with client.app.state.SessionLocal() as session:
        team_id = _team_id(session, "sales_growth")
        draft = create_constitution_draft(session, team_id, {"team_key": "sales_growth", "charter": "跳级发布"}, "owner")

        # draft → published is illegal (must go through reviewing → approved first).
        try:
            publish_constitution(session, draft.id, "owner")
        except BusinessError as exc:
            assert "cannot transition" in str(exc)
        else:
            raise AssertionError("publishing a draft directly must raise BusinessError")

        # draft → approved is also illegal (skips reviewing).
        try:
            approve_constitution(session, draft.id, "owner")
        except BusinessError as exc:
            assert "cannot transition" in str(exc)
        else:
            raise AssertionError("approving a draft directly must raise BusinessError")
        session.commit()
