import pytest
from ghostbrain.api.auth.providers.atlassian_api import AtlassianTokenProvider
from ghostbrain.api.auth.session import Session
from ghostbrain.api.auth.providers.base import NextAction


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    (tmp_path / "vault" / "90-meta").mkdir(parents=True)
    (tmp_path / "vault" / "90-meta" / "routing.yaml").write_text("contexts: [work]\n", encoding="utf-8")
    return tmp_path


def _sess(cid):
    return Session(id="s", connector_id=cid, status="waiting_input", next=NextAction(kind="need_input"))


def test_start_fields(env):
    action = AtlassianTokenProvider().start("jira", {})
    names = {f["name"] for f in action.fields}
    assert {"email", "token", "site"} <= names


def test_submit_registers_site_account(env, monkeypatch):
    import ghostbrain.api.auth.providers.atlassian_api as mod
    monkeypatch.setattr(mod, "_validate_myself", lambda email, token, site: {"displayName": "Me"})
    p = AtlassianTokenProvider()
    sess = _sess("jira")
    p.submit("jira", sess, {"email": "me@x.com", "token": "tok", "site": "acme.atlassian.net"})
    assert sess.status == "success"
    from ghostbrain import accounts
    from ghostbrain.connectors.atlassian._base import token_path
    assert accounts.get_account("jira", "acme.atlassian.net").options == {"email": "me@x.com"}
    assert token_path("acme.atlassian.net").read_text() == "tok"


def test_submit_bad_creds_errors(env, monkeypatch):
    import ghostbrain.api.auth.providers.atlassian_api as mod
    def boom(*a): raise RuntimeError("401")
    monkeypatch.setattr(mod, "_validate_myself", boom)
    p = AtlassianTokenProvider()
    sess = _sess("confluence")
    p.submit("confluence", sess, {"email": "me@x.com", "token": "bad", "site": "acme.atlassian.net"})
    assert sess.status == "error"
