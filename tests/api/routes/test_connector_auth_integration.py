"""End-to-end connector auth + disconnect integration test."""
import pytest
from fastapi.testclient import TestClient
from ghostbrain.api.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Create a test client with temp state/vault dirs and stubbed network."""
    # Set up temp directories for connector state
    state_dir = tmp_path / "state"
    vault_dir = tmp_path / "vault"
    state_dir.mkdir(parents=True, exist_ok=True)
    vault_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(state_dir))
    monkeypatch.setenv("VAULT_PATH", str(vault_dir))

    # Clear any SLACK_TOKEN_* env vars from the test environment
    # (the probe checks these as a fallback after checking token files,
    # so we need to clear them for tests that verify the "off" state)
    import os
    for key in list(os.environ.keys()):
        if key.startswith("SLACK_TOKEN_"):
            monkeypatch.delenv(key)

    # Create vault meta directory so probe doesn't fail
    (vault_dir / "90-meta").mkdir(parents=True, exist_ok=True)

    # Monkeypatch _slack_auth_test to avoid network calls
    import ghostbrain.api.auth.providers.paste_token as mod
    monkeypatch.setattr(
        mod,
        "_slack_auth_test",
        lambda t: {"user": "me", "team": "T"}
    )

    # Create app with fixed test token and set up client with auth header
    app = create_app(token="test-token-1234567890")
    client = TestClient(app)
    client.headers.update({"Authorization": "Bearer test-token-1234567890"})
    return client


def test_slack_connect_flow(client):
    """Test: slack auth flow reaches 'on' state via the router."""
    # Start auth session
    start = client.post("/v1/connectors/slack/auth/start", json={"params": {}})
    assert start.status_code == 200
    sid = start.json()["session_id"]

    # Submit auth with workspace slug and token
    sub = client.post(
        "/v1/connectors/slack/auth/submit",
        json={
            "session_id": sid,
            "data": {
                "workspace_slug": "work",
                "token": "xoxp-abc"
            }
        }
    )
    assert sub.status_code == 200
    assert sub.json()["status"] == "success"

    # Connector should now read 'on'
    conns_resp = client.get("/v1/connectors")
    assert conns_resp.status_code == 200
    conns = {c["id"]: c for c in conns_resp.json()}
    assert conns["slack"]["state"] == "on"


def test_disconnect_flips_off(client):
    """Test: deleting connector credentials flips state from on to off."""
    # Save a token directly (simulating a prior successful auth)
    from ghostbrain.connectors.slack.auth import save_token
    save_token("work", "xoxp-abc")

    # Verify connector is 'on'
    conns_resp = client.get("/v1/connectors")
    assert conns_resp.status_code == 200
    conns = {c["id"]: c for c in conns_resp.json()}
    assert conns["slack"]["state"] == "on"

    # Delete credentials
    del_resp = client.delete(
        "/v1/connectors/slack/credentials",
        params={"account": "work"}
    )
    assert del_resp.status_code == 200

    # Connector should now read 'off'
    conns_resp = client.get("/v1/connectors")
    assert conns_resp.status_code == 200
    conns = {c["id"]: c for c in conns_resp.json()}
    assert conns["slack"]["state"] == "off"
