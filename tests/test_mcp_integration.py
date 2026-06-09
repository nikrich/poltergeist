# tests/test_mcp_integration.py
import httpx
import pytest
from starlette.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.mcp import tools
from ghostbrain.mcp.client import SidecarClient, SidecarNotRunning


@pytest.fixture
def seeded_vault(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    note_dir = vault / "20-contexts" / "sanlam" / "notes"
    note_dir.mkdir(parents=True)
    (note_dir / "x.md").write_text(
        "---\ntitle: ASCP wizard\ncontext: sanlam\n---\n\nUse Cognito session refresh.\n"
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    return vault


def _client_for(app, token):
    # TestClient is an httpx.Client subclass with a built-in ASGI sync transport;
    # pass it directly so SidecarClient gets a real sync HTTP client for the ASGI app.
    http = TestClient(app, raise_server_exceptions=True)
    return SidecarClient(
        loader=lambda: {"port": 1, "token": token, "pid": 1, "version": "1.0.0"},
        http_client=http,
    )


def test_get_note_end_to_end(seeded_vault):
    app = create_app(token="test-token")
    client = _client_for(app, "test-token")
    out = tools.get_note(client, "20-contexts/sanlam/notes/x.md")
    assert "ASCP wizard" in out
    assert "Cognito session refresh" in out
    assert "context: sanlam" in out


def test_bad_token_is_rejected(seeded_vault):
    app = create_app(token="real-token")
    client = _client_for(app, "wrong-token")
    with pytest.raises(httpx.HTTPStatusError):
        tools.get_note(client, "20-contexts/sanlam/notes/x.md")


def test_not_running_path():
    client = SidecarClient(loader=lambda: None, http_client=httpx.Client())
    with pytest.raises(SidecarNotRunning):
        tools.get_note(client, "anything.md")
