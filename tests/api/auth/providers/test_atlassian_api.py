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


def test_submit_overwrites_stale_site_token_in_dotenv(env, monkeypatch):
    """A stale ATLASSIAN_TOKEN_<SLUG> in .env wins over the state file in
    auth_for_site, so reconnecting must replace it (file + running process)."""
    import os

    import ghostbrain.api.auth.providers.atlassian_api as mod
    from ghostbrain.api.repo.dotenv_store import env_path, read_env
    from ghostbrain.connectors.atlassian._base import auth_for_site

    env_path().parent.mkdir(parents=True, exist_ok=True)
    env_path().write_text("ATLASSIAN_EMAIL=old@x.com\nATLASSIAN_TOKEN_ACME=stale\nOTHER=1\n",
                          encoding="utf-8")
    monkeypatch.setenv("ATLASSIAN_EMAIL", "old@x.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_ACME", "stale")  # loaded at sidecar start
    monkeypatch.setattr(mod, "_validate_myself", lambda email, token, site: {})
    sess = _sess("jira")
    AtlassianTokenProvider().submit(
        "jira", sess, {"email": "me@x.com", "token": "fresh", "site": "acme.atlassian.net"})
    assert sess.status == "success"
    assert auth_for_site("acme.atlassian.net") == ("me@x.com", "fresh")
    env = read_env()
    assert env["ATLASSIAN_TOKEN_ACME"] == "fresh"
    assert env["ATLASSIAN_EMAIL"] == "old@x.com" and env["OTHER"] == "1"
    assert os.environ["ATLASSIAN_EMAIL"] == "old@x.com"


def test_submit_does_not_add_site_token_to_dotenv_when_absent(env, monkeypatch):
    import ghostbrain.api.auth.providers.atlassian_api as mod
    from ghostbrain.api.repo.dotenv_store import env_path

    monkeypatch.delenv("ATLASSIAN_TOKEN_ACME", raising=False)
    monkeypatch.setattr(mod, "_validate_myself", lambda email, token, site: {})
    AtlassianTokenProvider().submit(
        "jira", _sess("jira"), {"email": "me@x.com", "token": "fresh", "site": "acme.atlassian.net"})
    assert not env_path().exists()
