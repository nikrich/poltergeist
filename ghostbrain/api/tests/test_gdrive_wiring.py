from __future__ import annotations

from pathlib import Path


def test_google_provider_resolves_gdrive_module():
    from ghostbrain.api.auth.providers.google_oauth import _mod
    from ghostbrain.connectors.gdrive import auth

    assert _mod("gdrive") is auth


def test_gdrive_registered_on_google_provider():
    import ghostbrain.api.auth.providers.register_all  # noqa: F401
    from ghostbrain.api.auth import registry

    assert registry.provider_for("gdrive").pattern == "google_oauth"


def test_poll_registers_gdrive_account(monkeypatch, tmp_vault, tmp_state_dir):
    from ghostbrain import accounts
    from ghostbrain.api.auth.providers.google_oauth import GoogleProvider
    from ghostbrain.connectors.gdrive import auth

    monkeypatch.setattr(auth, "run_oauth_flow", lambda email: Path("/dev/null"))

    class S:
        _google_account = "me@x.com"
        status = error = account = next = None

    s = S()
    GoogleProvider().poll("gdrive", s)
    assert s.status == "success"
    assert accounts.get_account("gdrive", "me@x.com") is not None


def test_disconnect_removes_gdrive_token(tmp_state_dir):
    from ghostbrain.api.auth.disconnect import disconnect
    from ghostbrain.connectors.gdrive.auth import token_path

    p = token_path("me@x.com")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    disconnect("gdrive", "me@x.com")
    assert not p.exists()


def test_probe_sees_gdrive_token(tmp_state_dir):
    from ghostbrain.api.repo.connector_probe import probe
    from ghostbrain.connectors.gdrive.auth import token_path

    assert probe("gdrive").state == "off"
    p = token_path("me@x.com")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}")
    assert probe("gdrive").state == "on"


def test_gdrive_listed_in_connectors(client, auth_headers):
    rows = {c["id"]: c for c in client.get("/v1/connectors", headers=auth_headers).json()}
    assert rows["gdrive"]["displayName"] == "Google Drive"
