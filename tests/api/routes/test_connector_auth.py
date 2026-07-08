import pytest
from fastapi.testclient import TestClient
from ghostbrain.api.main import create_app
from ghostbrain.api import auth as auth_pkg
from ghostbrain.api.auth import registry
from ghostbrain.api.auth.providers.base import NextAction


class StubProvider:
    pattern = "stub"
    def start(self, connector_id, params):
        return NextAction(kind="need_input", fields=[{"name": "token", "label": "T", "type": "password"}])
    def submit(self, connector_id, session, data):
        session.status = "success"; session.account = "acct"
        return NextAction(kind="done")
    def poll(self, connector_id, session): pass
    def account_label(self, session): return "acct"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(registry, "provider_for", lambda cid: StubProvider())
    app = create_app(token="test-token-1234567890")
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test-token-1234567890"})
    return client


def test_start_then_submit(client):
    r = client.post("/v1/connectors/slack/auth/start", json={"params": {}})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert r.json()["next"]["kind"] == "need_input"

    r2 = client.post("/v1/connectors/slack/auth/submit", json={"session_id": sid, "data": {"token": "x"}})
    assert r2.status_code == 200
    assert r2.json()["status"] == "success"
    assert r2.json()["account"] == "acct"


def test_status_unknown_session_404(client):
    r = client.get("/v1/connectors/slack/auth/status", params={"session_id": "nope"})
    assert r.status_code == 404


def test_unknown_connector_404(client, monkeypatch):
    monkeypatch.setattr(registry, "provider_for", lambda cid: (_ for _ in ()).throw(KeyError(cid)))
    r = client.post("/v1/connectors/bogus/auth/start", json={"params": {}})
    assert r.status_code == 404


def test_submit_wrong_connector_404(client):
    """Start session on one connector, try to submit via another connector → 404."""
    # Start session under 'slack'
    r = client.post("/v1/connectors/slack/auth/start", json={"params": {}})
    assert r.status_code == 200
    sid = r.json()["session_id"]
    initial_status = r.json()["status"]

    # Try to submit via 'github' (wrong connector)
    r2 = client.post("/v1/connectors/github/auth/submit", json={"session_id": sid, "data": {"token": "x"}})
    assert r2.status_code == 404
    assert r2.json()["detail"] == "Unknown or expired auth session"

    # Verify session status unchanged on slack (provider not invoked)
    r3 = client.get("/v1/connectors/slack/auth/status", params={"session_id": sid})
    assert r3.status_code == 200
    assert r3.json()["status"] == initial_status  # Still "pending", not "success"


def test_cancel_wrong_connector_404(client):
    """Start session on one connector, try to cancel via another connector → 404."""
    # Start session under 'slack'
    r = client.post("/v1/connectors/slack/auth/start", json={"params": {}})
    assert r.status_code == 200
    sid = r.json()["session_id"]

    # Try to cancel via 'github' (wrong connector)
    r2 = client.post("/v1/connectors/github/auth/cancel", json={"session_id": sid})
    assert r2.status_code == 404

    # Verify session still exists on slack (was not cancelled)
    r3 = client.get("/v1/connectors/slack/auth/status", params={"session_id": sid})
    assert r3.status_code == 200  # Session still there
