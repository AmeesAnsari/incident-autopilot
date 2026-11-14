import json

import httpx2 as httpx
from fastapi.testclient import TestClient

from incident_autopilot.app import create_app
from incident_autopilot.itsm import MockITSM, ServiceNowClient
from incident_autopilot.store import Store


def client():
    itsm = MockITSM()
    return TestClient(create_app(Store(), itsm)), itsm


def prtg(status, device="gw-1", when="2026-11-14T08:00:00+00:00"):
    return {"device": device, "sensor": "Ping", "status": status, "message": "timeout",
            "datetime": when, "account": "AC-1"}


def test_prtg_lifecycle_over_http():
    api, itsm = client()
    assert api.post("/alerts/prtg", json=prtg("Down")).json()[0]["kind"] == "created"
    assert api.post("/alerts/prtg", json=prtg("Down")).json()[0]["kind"] == "duplicate"
    assert api.post("/alerts/prtg", json=prtg("Up", when="2026-11-14T08:10:00+00:00")).json()[0]["kind"] == "resolved"

    incidents = api.get("/incidents").json()
    assert len(incidents) == 1 and incidents[0]["status"] == "resolved"
    assert [a["kind"] for a in api.get("/actions").json()] == ["resolved", "duplicate", "created"]


def test_prtg_warning_is_ignored():
    api, itsm = client()
    assert api.post("/alerts/prtg", json=prtg("Warning")).json()[0]["kind"] == "ignored"
    assert itsm.calls == []


def test_prtg_missing_field_is_422():
    api, _ = client()
    body = prtg("Down")
    del body["account"]
    assert api.post("/alerts/prtg", json=body).status_code == 422


def test_generic_alert_validation():
    api, _ = client()
    assert api.post("/alerts", json={"source": "x", "account": "", "device": "d", "state": "down",
                                     "at": "2026-11-14T08:00:00Z"}).status_code == 422


def test_health_and_404():
    api, _ = client()
    assert api.get("/health").json() == {"ok": True, "itsm": "MockITSM", "open_incidents": 0}
    assert api.get("/incidents/99").status_code == 404


def test_servicenow_client_requests():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, json.loads(request.content or b"{}")))
        if request.method == "POST":
            return httpx.Response(201, json={"result": {"sys_id": "abc123"}})
        return httpx.Response(200, json={"result": {}})

    sn = ServiceNowClient("https://example.service-now.com", "u", "p", "NOC L1",
                          transport=httpx.MockTransport(handler))
    assert sn.create("Alarm", "details", "P3") == "abc123"
    sn.add_note("abc123", "note")
    sn.resolve("abc123", "done")

    assert seen[0][:2] == ("POST", "/api/now/table/incident")
    assert seen[0][2]["assignment_group"] == "NOC L1" and seen[0][2]["impact"] == "3"
    assert seen[1] == ("PATCH", "/api/now/table/incident/abc123", {"work_notes": "note"})
    assert seen[2][2]["state"] == "6" and seen[2][2]["close_notes"] == "done"
