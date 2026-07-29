from __future__ import annotations

TENANT = "00000000-0000-0000-0000-000000000001"


def _headers(tenant: str = TENANT):
    return {"X-Tenant-ID": tenant, "X-Actor-ID": "owner"}


def test_hr_people_team_seeded(client):
    teams = client.get("/v1/teams", headers=_headers()).json()
    hr = next((t for t in teams if t["team_key"] == "hr_people"), None)
    assert hr is not None
    assert hr["name"] == "HR 与人事专家团"
    # TeamConstitutionVersion loaded
    assert hr["constitution"] is not None
    assert hr["constitution"]["lead_role"]["key"] == "hr_director"
    # WorkflowVersion records for both default workflows
    workflow_keys = {w["workflow_key"] for w in hr["workflows"]}
    assert {"candidate_inquiry", "employee_relation_issue"} <= workflow_keys
    # AgentProfile records including the lead
    roles = {a["role_key"] for a in hr["agents"]}
    assert {"hr_director", "recruiter", "hr_communicator", "relation_specialist"} <= roles
    lead = next(a for a in hr["agents"] if a["role_key"] == "hr_director")
    assert lead["is_lead"] is True


def test_finance_ops_team_seeded(client):
    teams = client.get("/v1/teams", headers=_headers()).json()
    fin = next((t for t in teams if t["team_key"] == "finance_ops"), None)
    assert fin is not None
    assert fin["name"] == "财务与运营专家团"
    assert fin["constitution"]["lead_role"]["key"] == "finance_director"
    workflow_keys = {w["workflow_key"] for w in fin["workflows"]}
    assert {"invoice_inquiry", "payment_request"} <= workflow_keys
    roles = {a["role_key"] for a in fin["agents"]}
    assert {"finance_director", "ar_specialist", "ap_specialist", "finance_communicator"} <= roles
    lead = next(a for a in fin["agents"] if a["role_key"] == "finance_director")
    assert lead["is_lead"] is True


def test_new_team_skills_seeded(client):
    skills = client.get("/v1/skills", headers=_headers()).json()
    skill_map = {s["definition"]["skill_key"]: s for s in skills}
    expected = {
        "hr-lead-triage",
        "hr-candidate-screening",
        "hr-employee-communication",
        "hr-relation-investigation",
        "finance-lead-triage",
        "finance-ar-processing",
        "finance-ap-processing",
        "finance-communication",
    }
    for key in expected:
        assert key in skill_map, f"missing SkillRelease for {key}"
        release = skill_map[key]["release"]
        assert release["semantic_version"] == "1.0.0"
        assert release["status"] == "published"


def test_new_team_dispatch_routing(client):
    # A recruitment email whose body hits hr_people positive_signals (招聘/简历/面试)
    # and no other team's positive_signals, so dispatch scoring selects hr_people.
    msg = client.post("/v1/inbox/messages", headers=_headers(), json={
        "provider_message_id": "test:hr:routing:1",
        "sender": "candidate@example.com",
        "recipients": ["owner@example.com"],
        "subject": "招聘咨询",
        "body_text": "您好，我想了解贵司的招聘流程，请问如何投递简历和安排面试？",
    }).json()
    mail_id = msg["id"]

    decision = client.post(f"/v1/inbox/{mail_id}/dispatch", headers=_headers()).json()
    assert decision["id"]
    assert decision["status"] == "PROPOSED"

    dispatch_list = client.get("/v1/dispatch", headers=_headers()).json()
    entry = next(d for d in dispatch_list if d["decision"]["id"] == decision["id"])
    assert entry["suggested_team"]["team_key"] == "hr_people"
    # positive_signals produced a positive score, so confidence should be above the baseline
    assert decision["confidence"] > 55
