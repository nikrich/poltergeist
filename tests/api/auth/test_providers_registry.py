"""Connect flows register accounts; disconnect removes them."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from ghostbrain import accounts
from ghostbrain.api.auth.providers.base import NextAction
from ghostbrain.api.auth.session import Session


@pytest.fixture
def env(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text("contexts: [personal, agencyx]\n", encoding="utf-8")
    (root / "90-meta" / "accounts.yaml").write_text("version: 1\naccounts: []\n", encoding="utf-8")
    return root


def _session(cid: str) -> Session:
    return Session(id="s", connector_id=cid, status="pending", next=NextAction(kind="open_browser"))


def test_google_success_registers_gmail_account(env, monkeypatch):
    from ghostbrain.api.auth.providers.google_oauth import GoogleProvider
    from ghostbrain.connectors.gmail import auth as gauth

    monkeypatch.setattr(gauth, "run_oauth_flow", lambda email: Path("/tmp/x"))
    s = _session("gmail")
    s._google_account = "new@x.com"
    GoogleProvider().poll("gmail", s)
    assert s.status == "success"
    assert accounts.get_account("gmail", "new@x.com") is not None


def test_google_success_keeps_existing_context(env, monkeypatch):
    from ghostbrain.api.auth.providers.google_oauth import GoogleProvider
    from ghostbrain.connectors.calendar.google import auth as cauth

    accounts.upsert_account(accounts.Account("calendar_google", "me@agencyx.com", "agencyx"))
    monkeypatch.setattr(cauth, "run_oauth_flow", lambda email: Path("/tmp/x"))
    s = _session("calendar")
    s._google_account = "me@agencyx.com"
    GoogleProvider().poll("calendar", s)
    assert accounts.get_account("calendar_google", "me@agencyx.com").context == "agencyx"


def test_slack_success_registers_workspace_without_routing_write(env, monkeypatch):
    from ghostbrain.api.auth.providers import paste_token

    monkeypatch.setattr(paste_token, "_slack_auth_test", lambda t: {"user": "me", "team": "X"})
    s = _session("slack")
    paste_token.SlackTokenProvider().submit("slack", s, {"workspace_slug": "agencyx", "token": "xoxp-1"})
    assert s.status == "success"
    assert accounts.get_account("slack", "agencyx") is not None
    routing = yaml.safe_load((env / "90-meta" / "routing.yaml").read_text())
    assert "slack" not in routing


def test_atlassian_success_stores_site_identity_not_global_env(env, monkeypatch):
    from ghostbrain.api.auth.providers import atlassian_api
    from ghostbrain.api.repo.dotenv_store import read_env
    from ghostbrain.connectors.atlassian._base import token_path

    monkeypatch.setattr(atlassian_api, "_validate_myself", lambda e, t, s: {"emailAddress": e})
    s = _session("jira")
    atlassian_api.AtlassianTokenProvider().submit(
        "jira", s, {"email": "me@agencyx.com", "token": "tok", "site": "https://agencyx.atlassian.net/"})
    assert s.status == "success"
    acc = accounts.get_account("jira", "agencyx.atlassian.net")
    assert acc.options == {"email": "me@agencyx.com"}
    assert token_path("agencyx.atlassian.net").read_text() == "tok"
    assert "ATLASSIAN_EMAIL" not in read_env()


def test_ms_poll_registers_username_from_claims(env, monkeypatch):
    from ghostbrain.api.auth.providers import ms_device_code

    app = MagicMock()
    app.acquire_token_by_device_flow.return_value = {
        "access_token": "t", "id_token_claims": {"preferred_username": "second@agencyy.com"}}
    app.get_accounts.return_value = [{"username": "first@x.com"}, {"username": "second@agencyy.com"}]
    monkeypatch.setattr(ms_device_code, "_build_app", lambda cfg: app)
    monkeypatch.setattr(ms_device_code, "_app_config", lambda: {"client_id": "c", "tenant_id": "t"})
    s = _session("outlook_mail")
    s._ms_flow = {"user_code": "X"}
    ms_device_code.MicrosoftProvider().poll("outlook_mail", s)
    assert s.account == "second@agencyy.com"
    assert accounts.get_account("microsoft", "second@agencyy.com") is not None


def test_github_success_registers_login(env, monkeypatch):
    from ghostbrain.api.auth.providers import cli_login

    monkeypatch.setattr(cli_login, "_gh_logged_in", lambda: (True, "nikrich"))
    s = _session("github")
    cli_login.GitHubProvider().poll("github", s)
    assert accounts.get_account("github", "nikrich") is not None


def test_disconnect_removes_account_entry(env, tmp_path):
    from ghostbrain.api.auth.disconnect import disconnect
    from ghostbrain.connectors.atlassian._base import save_token, token_path

    accounts.upsert_account(accounts.Account("gmail", "a@x.com", "personal"))
    accounts.upsert_account(accounts.Account("jira", "agencyx.atlassian.net"))
    save_token("agencyx.atlassian.net", "tok")
    disconnect("gmail", "a@x.com")
    disconnect("jira", "agencyx.atlassian.net")
    assert accounts.list_accounts() == []
    assert not token_path("agencyx.atlassian.net").exists()


def test_disconnect_microsoft_account_removes_only_that_account(env, monkeypatch):
    from ghostbrain.api.auth import disconnect as dmod
    from ghostbrain.connectors.microsoft.graph import auth as ms_auth

    removed: list[str] = []
    monkeypatch.setattr(ms_auth, "remove_cached_account", lambda cfg, u: removed.append(u) or True)
    ms_auth.cache_location().parent.mkdir(parents=True, exist_ok=True)
    ms_auth.cache_location().write_text("cache")
    accounts.upsert_account(accounts.Account("microsoft", "a@x.com"))
    accounts.upsert_account(accounts.Account("microsoft", "b@y.com"))
    dmod.disconnect("teams_chat", "a@x.com")
    assert removed == ["a@x.com"]
    assert ms_auth.cache_location().exists()
    assert [a.id for a in accounts.list_accounts("microsoft")] == ["b@y.com"]
