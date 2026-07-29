"""Run the full Controlled Beta golden path without external credentials."""
from pathlib import Path
from fastapi.testclient import TestClient
from workbuddy.api.main import create_app

H={"X-Tenant-ID":"00000000-0000-0000-0000-000000000001","X-Actor-ID":"owner"}
db=Path("demo-flow.db")
if db.exists(): db.unlink()
app=create_app(f"sqlite:///{db}",auto_seed=True)
with TestClient(app) as c:
    c.post('/v1/demo/bootstrap',headers=H)
    mail=next(x for x in c.get('/v1/inbox',headers=H).json() if x['provider_message_id']=='demo:sales:1')
    mission=c.post(f"/v1/dispatch/{mail['dispatch']['id']}/confirm",headers=H,json={"team_key":"sales_growth"}).json()
    for action in ['accept','plan','approve-plan','start']:
        mission=c.post(f"/v1/missions/{mission['id']}/{action}",headers=H,json={"expected_version":mission['version'],"reason":"controlled beta golden path"}).json()
    for _ in range(20):
        detail=c.get(f"/v1/missions/{mission['id']}",headers=H).json()
        if all(x['status']=='ACCEPTED' for x in detail['work_items']): break
        submitted=next((x for x in detail['work_items'] if x['status']=='SUBMITTED'),None)
        if submitted:
            r=c.post(f"/v1/work-items/{submitted['id']}/review",headers=H,json={"decision":"accept","reason":"quality gate passed"})
            r.raise_for_status(); continue
        item=next(x for x in detail['work_items'] if x['status'] in {'READY','ASSIGNED','REVISION_REQUIRED'})
        run=c.post(f"/v1/work-items/{item['id']}/start",headers=H).json()
        r=c.post(f"/v1/agent-runs/{run['id']}/execute",headers=H,json={"force_provider":"configured"})
        r.raise_for_status()
    detail=c.get(f"/v1/missions/{mission['id']}",headers=H).json(); mission=detail['mission']
    result=c.post(f"/v1/missions/{mission['id']}/lead-review",headers=H,json={"expected_version":mission['version'],"reason":"lead integrated outputs"}).json()
    approval=result['approval']
    c.post(f"/v1/approvals/{approval['id']}/decision",headers=H,json={"decision":"approve","reason":"owner approved exact action"}).raise_for_status()
    op=c.post('/v1/operations',headers=H,json={"approval_id":approval['id'],"operation_key":"controlled-beta-demo-send"}).json()
    op=c.post(f"/v1/operations/{op['id']}/execute",headers=H,json={"simulate_unknown":False}).json()
    print({
        "mission_id":mission['id'],
        "operation_status":op['status'],
        "demo_mode":op['demo_mode'],
        "quality":c.get('/v1/quality',headers=H).json(),
        "readiness":c.get('/v1/beta/readiness',headers=H).json(),
        "audit":c.get('/v1/audit/verify',headers=H).json(),
    })
