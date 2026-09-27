from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ghostbrain import accounts_health
from ghostbrain.connectors.microsoft.graph import auth, multi

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
CFG = {"client_id": "cid", "tenant_id": "default-tenant"}


def test_get_token_selects_the_named_account():
    app = MagicMock()
    app.get_accounts.return_value = [{"username": "b@y.com"}]
    app.acquire_token_silent.return_value = {"access_token": "tok-b"}
    with patch.object(auth, "_build_app", return_value=app) as build:
        assert auth.get_token(CFG, username="b@y.com", tenant_id="tenant-y") == "tok-b"
    build.assert_called_once_with(CFG, "tenant-y")
    app.get_accounts.assert_called_once_with(username="b@y.com")
    app.acquire_token_silent.assert_called_once_with(auth.resolve_scopes(CFG), account={"username": "b@y.com"})


def test_get_token_without_username_uses_first_cached_account():
    app = MagicMock()
    app.get_accounts.return_value = [{"username": "first@x.com"}, {"username": "second@y.com"}]
    app.acquire_token_silent.return_value = {"access_token": "tok-first"}
    with patch.object(auth, "_build_app", return_value=app) as build:
        assert auth.get_token(CFG, None, None) == "tok-first"
    build.assert_called_once_with(CFG, None)
    app.get_accounts.assert_called_once_with()
    app.acquire_token_silent.assert_called_once_with(auth.resolve_scopes(CFG), account={"username": "first@x.com"})


def test_get_token_unknown_username_raises():
    app = MagicMock()
    app.get_accounts.return_value = []
    with patch.object(auth, "_build_app", return_value=app), pytest.raises(auth.MicrosoftAuthError):
        auth.get_token(CFG, username="nobody@y.com")


def test_username_from_result_prefers_id_token_claims():
    app = MagicMock()
    app.get_accounts.return_value = [{"username": "first@x.com"}]
    assert auth.username_from_result({"id_token_claims": {"preferred_username": "new@y.com"}}, app) == "new@y.com"
    assert auth.username_from_result({}, app) == "first@x.com"
    app.get_accounts.return_value = []
    assert auth.username_from_result({}, app) == "your account"


def test_cached_usernames_and_remove_cached_account():
    app = MagicMock()
    app.get_accounts.return_value = [{"username": "a@x.com"}, {"home_account_id": "no-name"}]
    with patch.object(auth, "_build_app", return_value=app):
        assert auth.cached_usernames(CFG) == ["a@x.com"]
        app.get_accounts.return_value = [{"username": "a@x.com"}]
        assert auth.remove_cached_account(CFG, "a@x.com") is True
        app.get_accounts.return_value = []
        assert auth.remove_cached_account(CFG, "gone@x.com") is False
    app.remove_account.assert_called_once_with({"username": "a@x.com"})


def test_run_device_flow_adds_account_under_tenant_and_returns_new_username():
    app = MagicMock()
    app.initiate_device_flow.return_value = {"user_code": "ABC", "message": "go"}
    app.acquire_token_by_device_flow.return_value = {
        "access_token": "t", "id_token_claims": {"preferred_username": "new@y.com"},
    }
    app.get_accounts.return_value = [{"username": "old@x.com"}, {"username": "new@y.com"}]
    with patch.object(auth, "_build_app", return_value=app) as build:
        assert auth.run_device_flow(CFG, tenant_id="t-y") == "new@y.com"
    build.assert_called_once_with(CFG, "t-y")


def test_fetch_per_account_tags_and_isolates(monkeypatch):
    def fake_token(config, username=None, tenant_id=None):
        if username == "expired@y.com":
            raise auth.MicrosoftAuthError("no cached sign-in")
        return f"tok-{username}"

    monkeypatch.setattr(multi, "get_token", fake_token)
    monkeypatch.setattr(multi, "GraphClient", lambda token: token)
    cfg = {**CFG, "accounts": [{"username": "a@x.com", "tenant_id": None},
                               {"username": "expired@y.com", "tenant_id": "t"}]}
    events = multi.fetch_per_account("outlook_mail", cfg, lambda client: [{"id": client, "metadata": {}}])
    assert events == [{"id": "tok-a@x.com", "metadata": {"accountId": "a@x.com"}}]
    assert accounts_health.health_for("outlook_mail", "expired@y.com")["status"] == "auth_required"
    assert accounts_health.health_for("outlook_mail", "a@x.com")["status"] == "ok"


def test_fetch_per_account_fallback_entry_uses_first_cached_account(monkeypatch):
    """R1: no registry accounts -> one {username: None} entry: first cached
    MSAL sign-in, no accountId tag, health recorded under 'default'."""
    calls = []

    def fake_token(config, username=None, tenant_id=None):
        calls.append((username, tenant_id))
        return "tok-first"

    monkeypatch.setattr(multi, "get_token", fake_token)
    monkeypatch.setattr(multi, "GraphClient", lambda token: token)
    cfg = {**CFG, "accounts": [{"username": None, "tenant_id": None}]}
    assert multi.ms_accounts(cfg) == [{"username": None, "tenant_id": None}]
    events = multi.fetch_per_account("teams_meetings", cfg, lambda client: [{"id": client, "metadata": {}}])
    assert calls == [(None, None)]
    assert events == [{"id": "tok-first", "metadata": {}}]
    assert accounts_health.health_for("teams_meetings", "default")["status"] == "ok"


def test_ms_accounts_drops_junk_and_any_token(monkeypatch):
    cfg = {**CFG, "accounts": ["junk", None, {"username": "a@x.com"}, {"username": None, "tenant_id": None}]}
    assert multi.ms_accounts(cfg) == [{"username": "a@x.com"}, {"username": None, "tenant_id": None}]
    seen = []
    monkeypatch.setattr(multi, "have_token", lambda c, u=None, t=None: seen.append(u) or u is None)
    assert multi.any_token(cfg) is True
    assert seen == ["a@x.com", None]
    monkeypatch.setattr(multi, "have_token", lambda c, u=None, t=None: False)
    assert multi.any_token(cfg) is False


def test_outlook_connector_multi_account(monkeypatch, tmp_path: Path):
    from ghostbrain.connectors.microsoft.outlook_mail import OutlookMailConnector

    class FakeClient:
        def __init__(self, token):
            self.token = token

        def get_all(self, path, params, max_items):
            return [{"id": f"m-{self.token}", "subject": "hi", "isRead": False,
                     "from": {"emailAddress": {"address": "bob@ok.com"}}}]

    monkeypatch.setattr(multi, "get_token", lambda c, username=None, tenant_id=None: username)
    monkeypatch.setattr(multi, "GraphClient", FakeClient)
    c = OutlookMailConnector(
        config={**CFG, "relevance_gate": False,
                "accounts": [{"username": "a@x.com"}, {"username": "b@y.com"}]},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )
    events = c.fetch(EPOCH)
    assert sorted(e["metadata"]["accountId"] for e in events) == ["a@x.com", "b@y.com"]


def test_teams_meetings_connector_fallback_account(monkeypatch, tmp_path: Path):
    from ghostbrain.connectors.microsoft.teams_meetings import TeamsMeetingsConnector

    client = MagicMock()
    client.get.side_effect = [
        {"value": [{"id": "m1", "subject": "Standup"}]},
        {"value": [{"id": "t1", "createdDateTime": "2026-06-03T10:00:00Z"}]},
    ]
    monkeypatch.setattr(multi, "get_token", lambda c, username=None, tenant_id=None: "tok")
    monkeypatch.setattr(multi, "GraphClient", lambda token: client)
    c = TeamsMeetingsConnector(
        config={**CFG, "meetings": ["123456"], "accounts": [{"username": None, "tenant_id": None}]},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )
    monkeypatch.setattr(c, "_fetch_transcript_text", lambda client, mid, tid: "WEBVTT")
    events = c.fetch(EPOCH)
    assert [e["id"] for e in events] == ["microsoft:transcript:m1:t1"]
    assert "accountId" not in events[0]["metadata"]
    assert accounts_health.health_for("teams_meetings", "default")["status"] == "ok"


@pytest.mark.parametrize("name", ["outlook_mail", "teams_chat", "teams_meetings"])
def test_runner_builds_accounts_from_registry(tmp_path: Path, name: str):
    import importlib

    runner = importlib.import_module(f"ghostbrain.connectors.microsoft.{name}.runner")
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text("contexts: [agencyy]\n", encoding="utf-8")
    (root / "90-meta" / "accounts.yaml").write_text(yaml.safe_dump({"version": 1, "accounts": [
        {"connector": "microsoft", "id": "me@agencyy.com", "options": {"tenant_id": "t-y"}},
    ]}), encoding="utf-8")
    routing = {"microsoft": {**CFG, name: {}}}
    c = runner._build(routing, tmp_path / "q", tmp_path / "s")
    assert c.config["accounts"] == [{"username": "me@agencyy.com", "tenant_id": "t-y"}]
    assert c.config["client_id"] == "cid"
    # R1: empty registry keeps syncing via the first cached MSAL sign-in.
    (root / "90-meta" / "accounts.yaml").write_text("version: 1\naccounts: []\n", encoding="utf-8")
    c = runner._build(routing, tmp_path / "q", tmp_path / "s")
    assert c is not None
    assert c.config["accounts"] == [{"username": None, "tenant_id": None}]
    # Block missing -> still skipped.
    assert runner._build({"microsoft": dict(CFG)}, tmp_path / "q", tmp_path / "s") is None


def test_auth_cli_registers_account_with_tenant(monkeypatch):
    from ghostbrain.connectors.microsoft.graph import auth_cli

    got = {}
    monkeypatch.setattr(auth_cli, "_load_microsoft_config", lambda: dict(CFG))
    monkeypatch.setattr(auth_cli, "run_device_flow",
                        lambda cfg, tenant_id=None: got.setdefault("tenant", tenant_id) and "new@y.com")
    monkeypatch.setattr("ghostbrain.accounts.ensure_account",
                        lambda c, i, *, options=None, **kw: got.update(acct=(c, i, options)))
    monkeypatch.setattr("sys.argv", ["ghostbrain-microsoft-auth", "--tenant", "t-y"])
    auth_cli.main()
    assert got["tenant"] == "t-y"
    assert got["acct"] == ("microsoft", "new@y.com", {"tenant_id": "t-y"})


def test_auth_cli_does_not_register_placeholder_username(monkeypatch):
    from ghostbrain.connectors.microsoft.graph import auth_cli

    registered = []
    monkeypatch.setattr(auth_cli, "_load_microsoft_config", lambda: dict(CFG))
    monkeypatch.setattr(auth_cli, "run_device_flow", lambda cfg, tenant_id=None: auth.UNKNOWN_USERNAME)
    monkeypatch.setattr("ghostbrain.accounts.ensure_account",
                        lambda *a, **kw: registered.append(a))
    monkeypatch.setattr("sys.argv", ["ghostbrain-microsoft-auth"])
    auth_cli.main()
    assert registered == []


def test_username_from_result_placeholder_is_the_constant():
    app = MagicMock()
    app.get_accounts.return_value = [{"home_account_id": "x"}]
    assert auth.username_from_result({}, app) == auth.UNKNOWN_USERNAME == "your account"
