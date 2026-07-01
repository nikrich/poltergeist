# ghostbrain/api/tests/test_ms_auth_routes.py
from __future__ import annotations

from ghostbrain.connectors.microsoft.graph.interactive_auth import AuthState


def _install_fake_holder(client, *, status_state, started=None):
    """Replace the route's holder with a stub on the live app.state."""
    app = client.app

    class Holder:
        def __init__(self):
            self.started = False

        def start(self, config):
            self.started = True
            if started == "already":
                from ghostbrain.connectors.microsoft.graph.interactive_auth import (
                    AlreadyRunning,
                )
                raise AlreadyRunning("already")

        def status(self, config):
            return status_state

        def disconnect(self, config):
            self.disconnected = True

    holder = Holder()
    app.state.ms_auth = holder
    return holder


def test_status_reports_connected(client, auth_headers):
    _install_fake_holder(client, status_state=AuthState("connected", "me@tenant"))
    r = client.get("/v1/connectors/microsoft/auth/status", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"state": "connected", "account": "me@tenant", "error": None}


def test_start_returns_pending(client, auth_headers):
    h = _install_fake_holder(client, status_state=AuthState("pending"))
    r = client.post("/v1/connectors/microsoft/auth/start", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["state"] == "pending"
    assert h.started is True


def test_start_conflict_when_already_running(client, auth_headers):
    _install_fake_holder(client, status_state=AuthState("pending"), started="already")
    r = client.post("/v1/connectors/microsoft/auth/start", headers=auth_headers)
    assert r.status_code == 409


def test_disconnect_resets(client, auth_headers):
    h = _install_fake_holder(client, status_state=AuthState("idle"))
    r = client.post("/v1/connectors/microsoft/auth/disconnect", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"state": "idle"}
    assert getattr(h, "disconnected", False) is True
