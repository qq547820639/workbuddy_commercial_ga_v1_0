# UNKNOWN recovery is also covered by the domain state-machine test. The API path is
# exercised in manual acceptance because it requires completing the approval flow.

def test_gmail_connector_reports_missing_credentials(client):
    r = client.get("/v1/connectors/gmail/start")
    assert r.status_code == 200
    assert r.json()["configured"] is False
