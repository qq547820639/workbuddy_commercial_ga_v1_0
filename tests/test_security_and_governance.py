from __future__ import annotations

from io import BytesIO
from workbuddy.db.models import Tenant


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
