"""InteractiveAuth holder. MSAL app is injected; no real browser/network."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ghostbrain.connectors.microsoft.graph.interactive_auth import (
    AlreadyRunning,
    AuthState,
    InteractiveAuth,
)

CFG = {"client_id": "c", "tenant_id": "t"}


def _fake_app(*, token=True, accounts=("me@tenant",), error=None):
    app = MagicMock()
    app.acquire_token_interactive.return_value = (
        {"access_token": "x"} if token else {"error": "access_denied",
                                             "error_description": error or "denied"}
    )
    app.get_accounts.return_value = [{"username": u} for u in accounts]
    return app


def test_start_then_connected_sets_account(monkeypatch):
    app = _fake_app()
    auth = InteractiveAuth(app_factory=lambda cfg: app)
    auth.start(CFG)
    auth.wait()
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.graph.interactive_auth.have_token",
        lambda cfg: True,
    )
    st = auth.status(CFG)
    assert st == AuthState(state="connected", account="me@tenant")


def test_failed_signin_maps_to_error(monkeypatch):
    app = _fake_app(token=False, error="consent required")
    auth = InteractiveAuth(app_factory=lambda cfg: app)
    auth.start(CFG)
    auth.wait()
    st = auth.status(CFG)
    assert st.state == "error"
    assert "consent required" in st.error


def test_second_start_while_running_raises(monkeypatch):
    import threading

    gate = threading.Event()
    app = MagicMock()
    app.acquire_token_interactive.side_effect = lambda *a, **k: (gate.wait(2)
                                                                 or {"access_token": "x"})
    app.get_accounts.return_value = [{"username": "me@tenant"}]
    auth = InteractiveAuth(app_factory=lambda cfg: app)
    auth.start(CFG)
    try:
        with pytest.raises(AlreadyRunning):
            auth.start(CFG)
    finally:
        gate.set()
        auth.wait()


def test_status_idle_when_no_flow_and_no_token(monkeypatch):
    auth = InteractiveAuth(app_factory=lambda cfg: _fake_app())
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.graph.interactive_auth.have_token",
        lambda cfg: False,
    )
    assert auth.status(CFG) == AuthState(state="idle")


def test_disconnect_removes_accounts_and_clears_cache(tmp_path, monkeypatch):
    app = _fake_app()
    cache = tmp_path / "token_cache.bin"
    cache.write_text("blob")
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.graph.interactive_auth.cache_location",
        lambda: cache,
    )
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.graph.interactive_auth.have_token",
        lambda cfg: False,
    )
    auth = InteractiveAuth(app_factory=lambda cfg: app)
    auth.disconnect(CFG)
    app.remove_account.assert_called_once()
    assert not cache.exists()
    assert auth.status(CFG).state == "idle"
