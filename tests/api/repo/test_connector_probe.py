import os
from pathlib import Path
import pytest
from ghostbrain.api.repo.connector_probe import probe, ProbeResult


@pytest.fixture
def state(tmp_path, monkeypatch):
    d = tmp_path / "state"
    d.mkdir()
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(d))
    # Clean up any SLACK_TOKEN_* env vars that might be in the environment
    for key in list(os.environ.keys()):
        if key.startswith("SLACK_TOKEN_"):
            monkeypatch.delenv(key, raising=False)
    return d


def test_gmail_off_when_no_token(state):
    r = probe("gmail")
    assert r.state == "off"
    assert r.account is None


def test_gmail_on_when_token_present(state):
    (state / "gmail.you_at_gmail_com.token").write_text("{}")
    r = probe("gmail")
    assert r.state == "on"
    assert r.account == "you@gmail.com"


def test_slack_off_when_no_token(state):
    assert probe("slack").state == "off"


def test_slack_on_when_token_file_present(state):
    (state / "slack.work.token").write_text("xoxp-abc\n")
    assert probe("slack").state == "on"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(v))
    for key in ("ATLASSIAN_EMAIL",) + tuple(
        k for k in os.environ if k.startswith("ATLASSIAN_TOKEN")
    ):
        monkeypatch.delenv(key, raising=False)
    return v


def test_jira_off_when_no_creds_no_routing(state, vault):
    assert probe("jira").state == "off"


def test_jira_on_when_creds_and_routing_site(state, vault, monkeypatch):
    from ghostbrain.api.repo.routing import merge_routing

    monkeypatch.setenv("ATLASSIAN_EMAIL", "me@x.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_ACME", "tok")
    merge_routing({"jira": {"sites": {"acme.atlassian.net": "needs_review"}}})

    r = probe("jira")
    assert r.state == "on"
    assert r.account == "me@x.com"


def test_confluence_off_when_creds_but_no_confluence_routing(state, vault, monkeypatch):
    from ghostbrain.api.repo.routing import merge_routing

    monkeypatch.setenv("ATLASSIAN_EMAIL", "me@x.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_ACME", "tok")
    merge_routing({"jira": {"sites": {"acme.atlassian.net": "needs_review"}}})

    assert probe("confluence").state == "off"


def test_jira_off_after_routing_sites_removed(state, vault, monkeypatch):
    from ghostbrain.api.repo.routing import merge_routing, remove_routing_path

    monkeypatch.setenv("ATLASSIAN_EMAIL", "me@x.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_ACME", "tok")
    merge_routing({"jira": {"sites": {"acme.atlassian.net": "needs_review"}}})
    assert probe("jira").state == "on"

    remove_routing_path("jira.sites")
    assert probe("jira").state == "off"
