import json
import pytest
from ghostbrain.api.auth.providers.google_oauth import GoogleProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "state").mkdir()
    return tmp_path / "state"


def _sess(cid):
    return Session(id="s", connector_id=cid, status="pending", next=NextAction(kind="need_input"))


def test_start_asks_for_client_json_when_missing(state):
    action = GoogleProvider().start("gmail", {})
    names = {f["name"] for f in (action.fields or [])}
    assert "client_json" in names


def test_submit_client_json_then_asks_account(state):
    p = GoogleProvider()
    sess = _sess("gmail")
    client = json.dumps({"installed": {"client_id": "x", "client_secret": "y",
                        "auth_uri": "a", "token_uri": "t", "redirect_uris": ["http://localhost"]}})
    action = p.submit("gmail", sess, {"client_json": client})
    from ghostbrain.connectors.gmail.auth import oauth_client_path
    assert oauth_client_path().exists()
    assert action.kind == "need_input"
    assert any(f["name"] == "account" for f in action.fields)


def test_start_asks_account_when_client_present(state):
    from ghostbrain.connectors.gmail.auth import oauth_client_path
    oauth_client_path().write_text("{}")
    action = GoogleProvider().start("gmail", {})
    assert any(f["name"] == "account" for f in (action.fields or []))
