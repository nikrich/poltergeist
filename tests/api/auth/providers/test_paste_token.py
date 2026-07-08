import pytest
from ghostbrain.api.auth.providers.paste_token import SlackTokenProvider, JoplinTokenProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    return tmp_path


def _sess(cid):
    return Session(id="s", connector_id=cid, status="waiting_input", next=NextAction(kind="need_input"))


def test_slack_start_asks_for_slug_and_token(state):
    action = SlackTokenProvider().start("slack", {})
    names = {f["name"] for f in action.fields}
    assert {"workspace_slug", "token"} <= names


def test_slack_submit_saves_token(state, monkeypatch):
    # stub auth.test so no network
    import ghostbrain.api.auth.providers.paste_token as mod
    monkeypatch.setattr(mod, "_slack_auth_test", lambda t: {"user": "me", "team": "T"})
    p = SlackTokenProvider()
    sess = _sess("slack")
    action = p.submit("slack", sess, {"workspace_slug": "work", "token": "xoxp-abc"})
    assert sess.status == "success"
    from ghostbrain.connectors.slack.auth import token_path
    assert token_path("work").exists()


def test_slack_submit_rejects_bad_prefix(state):
    p = SlackTokenProvider()
    sess = _sess("slack")
    p.submit("slack", sess, {"workspace_slug": "work", "token": "not-a-token"})
    assert sess.status == "error"


def test_joplin_submit_saves_token_to_routing(state, monkeypatch):
    import ghostbrain.api.auth.providers.paste_token as mod
    monkeypatch.setattr(mod, "_joplin_ping", lambda host, token: True)
    p = JoplinTokenProvider()
    sess = _sess("joplin")
    p.submit("joplin", sess, {"token": "abc", "host": "http://localhost:41184"})
    assert sess.status == "success"
    from ghostbrain.api.repo.routing import load_routing
    assert load_routing()["joplin"]["token"] == "abc"
