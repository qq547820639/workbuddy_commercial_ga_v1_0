from __future__ import annotations

H={"X-Tenant-ID":"00000000-0000-0000-0000-000000000001","X-Actor-ID":"owner","X-Correlation-ID":"test-correlation-001"}

def _ready_mission(client):
    client.post('/v1/demo/bootstrap',headers=H)
    msg=next(x for x in client.get('/v1/inbox',headers=H).json() if x['provider_message_id']=='demo:sales:1')
    m=client.post(f"/v1/dispatch/{msg['dispatch']['id']}/confirm",headers=H,json={'team_key':'sales_growth'}).json()
    m=client.post(f"/v1/missions/{m['id']}/accept",headers=H,json={'expected_version':m['version'],'reason':'accept'}).json()
    m=client.post(f"/v1/missions/{m['id']}/plan",headers=H,json={'expected_version':m['version'],'reason':'plan'}).json()
    return client.post(f"/v1/missions/{m['id']}/approve-plan",headers=H,json={'expected_version':m['version'],'reason':'approve'}).json()

def test_global_pause_blocks_execution(client):
    mission=_ready_mission(client)
    response=client.post('/v1/controls',headers=H,json={'scope_type':'company','scope_id':'*','paused':True,'reason':'emergency stop'})
    assert response.status_code==200
    blocked=client.post(f"/v1/missions/{mission['id']}/start",headers=H,json={'expected_version':mission['version'],'reason':'start'})
    assert blocked.status_code==422
    client.post('/v1/controls',headers=H,json={'scope_type':'company','scope_id':'*','paused':False,'reason':'resume'})
    ok=client.post(f"/v1/missions/{mission['id']}/start",headers=H,json={'expected_version':mission['version'],'reason':'start'})
    assert ok.status_code==200

def test_privacy_delete_preserves_audit(client):
    client.post('/v1/demo/bootstrap',headers=H)
    before=len(client.get('/v1/audit',headers=H).json())
    assert before>0
    deleted=client.post('/v1/privacy/delete-operational-data',headers=H,json={'confirmation':'DELETE OPERATIONAL DATA'})
    assert deleted.status_code==200
    assert client.get('/v1/inbox',headers=H).json()==[]
    after=client.get('/v1/audit',headers=H).json()
    assert len(after)>=before
    assert any(x['action']=='privacy.operational_data_deleted' for x in after)
    assert client.get('/v1/audit/verify',headers=H).json()['valid'] is True

def test_correlation_id_is_returned_and_audited(client):
    response=client.post('/v1/demo/bootstrap',headers=H)
    assert response.headers['X-Correlation-ID']=='test-correlation-001'
    events=client.get('/v1/audit',headers=H).json()
    assert any(e['correlation_id']=='test-correlation-001' for e in events)
