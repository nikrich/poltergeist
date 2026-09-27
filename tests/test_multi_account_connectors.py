"""Registry-driven connectors: two accounts, one broken -> the other still runs."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ghostbrain import accounts_health


@pytest.fixture
def v(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts: [personal, agencyx]\ngmail:\n  denylist_domains: ['*.spam.com']\n  relevance_gate: false\n",
        encoding="utf-8",
    )
    return root


def write_accounts(root: Path, entries: list[dict]) -> None:
    (root / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": entries}), encoding="utf-8"
    )


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


# --------------------------------------------------------------------- gmail

def test_gmail_runner_builds_from_registry(v, tmp_path):
    from ghostbrain.connectors.gmail import runner

    write_accounts(v, [
        {"connector": "gmail", "id": "a@x.com", "options": {"unread_lookback_hours": 48}},
        {"connector": "gmail", "id": "off@x.com", "enabled": False},
    ])
    routing = yaml.safe_load((v / "90-meta" / "routing.yaml").read_text())
    c = runner._build(routing, tmp_path / "q", tmp_path / "s")
    assert [a.email for a in c.accounts] == ["a@x.com"]
    assert c.accounts[0].unread_lookback_hours == 48
    assert c.denylist == ["*.spam.com"]


def test_gmail_runner_skips_without_accounts(v, tmp_path):
    from ghostbrain.connectors.gmail import runner

    write_accounts(v, [])
    assert runner._build({}, tmp_path / "q", tmp_path / "s") is None


def test_gmail_one_broken_account_does_not_stop_the_other(tmp_path, monkeypatch):
    from ghostbrain.connectors.gmail import connector as gm
    from ghostbrain.connectors.gmail.auth import GmailAuthError

    c = gm.GmailConnector(
        config={"accounts": {"good@x.com": {}, "expired@x.com": {}}, "relevance_gate": False},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )

    def fake_fetch(acc):
        if acc.email == "expired@x.com":
            raise GmailAuthError("refresh token rejected")
        return [gm._normalize_thread({
            "id": "t1",
            "messages": [{"threadId": "t1", "internalDate": "1790000000000", "labelIds": ["UNREAD"],
                          "payload": {"headers": [{"name": "Subject", "value": "hi"},
                                                  {"name": "From", "value": "Bob <bob@ok.com>"}]}}],
        }, account=acc.email)]

    monkeypatch.setattr(c, "_fetch_account", fake_fetch)
    events = c.fetch(EPOCH)
    assert [e["metadata"]["accountId"] for e in events] == ["good@x.com"]
    assert accounts_health.health_for("gmail", "expired@x.com")["status"] == "auth_required"
    assert accounts_health.health_for("gmail", "good@x.com")["status"] == "ok"


def test_gmail_health_check_true_when_any_account_usable(tmp_path, monkeypatch):
    from ghostbrain.connectors.gmail import connector as gm
    from ghostbrain.connectors.gmail.auth import GmailAuthError

    def creds(email):
        if email == "expired@x.com":
            raise GmailAuthError("nope")
        return object()

    monkeypatch.setattr(gm, "load_credentials", creds)
    c = gm.GmailConnector(config={"accounts": {"expired@x.com": {}, "good@x.com": {}}},
                          queue_dir=tmp_path / "q", state_dir=tmp_path / "s")
    assert c.health_check() is True
    c2 = gm.GmailConnector(config={"accounts": {"expired@x.com": {}}},
                           queue_dir=tmp_path / "q", state_dir=tmp_path / "s")
    assert c2.health_check() is False


def test_gmail_auth_cli_registers_account(v, monkeypatch, tmp_path):
    from ghostbrain import accounts
    from ghostbrain.connectors.gmail import auth_cli

    write_accounts(v, [])
    monkeypatch.setattr(auth_cli, "run_oauth_flow", lambda email: tmp_path / "tok")
    monkeypatch.setattr("sys.argv", ["ghostbrain-gmail-auth", "new@x.com"])
    auth_cli.main()
    acc = accounts.get_account("gmail", "new@x.com")
    assert acc is not None and acc.context is None


# ------------------------------------------------------------------ calendar

def test_calendar_google_config_from_registry(v):
    from ghostbrain.connectors.calendar import runner

    write_accounts(v, [
        {"connector": "calendar_google", "id": "a@agencyx.com", "context": "agencyx",
         "options": {"calendars": ["primary", "team@group.calendar.google.com"]}},
        {"connector": "calendar_google", "id": "b@x.com"},
    ])
    assert runner.google_config() == {
        "accounts": {"a@agencyx.com": "agencyx", "b@x.com": ""},
        "calendars_per_account": {"a@agencyx.com": ["primary", "team@group.calendar.google.com"]},
    }
    write_accounts(v, [])
    assert runner.google_config() is None


def test_calendar_google_one_broken_account(tmp_path, monkeypatch):
    from ghostbrain.connectors.calendar.google import GoogleCalendarConnector
    from ghostbrain.connectors.calendar.google.auth import GoogleAuthError

    c = GoogleCalendarConnector(
        config={"accounts": {"good@x.com": "", "expired@x.com": ""}},
        queue_dir=tmp_path / "q", state_dir=tmp_path / "s",
    )

    def fake(email, tmin, tmax):
        if email == "expired@x.com":
            raise GoogleAuthError("expired")
        return [{"id": "calendar:google:good@x.com:1", "metadata": {"account": email, "accountId": email}}]

    monkeypatch.setattr(c, "_fetch_account", fake)
    events = c.fetch(EPOCH)
    assert len(events) == 1
    assert accounts_health.health_for("calendar", "expired@x.com")["status"] == "auth_required"


def test_calendar_runner_all_google_accounts_failed(v, monkeypatch):
    """All google accounts failing: run reports AllAccountsFailed with the
    per-account summary, and google's last_run is not advanced."""
    from ghostbrain.connectors.calendar import runner
    from ghostbrain.connectors.calendar.google import GoogleCalendarConnector
    from ghostbrain.connectors.calendar.google.auth import GoogleAuthError
    from ghostbrain.paths import state_dir

    write_accounts(v, [{"connector": "calendar_google", "id": "expired@x.com"}])

    def fake(self, email, tmin, tmax):
        raise GoogleAuthError("expired")

    monkeypatch.setattr(GoogleCalendarConnector, "_fetch_account", fake)
    res = runner.run()
    assert res.ok is False and res.error_type == "AllAccountsFailed"
    assert res.error.startswith("google: all calendar accounts failed")
    assert res.details["accounts"] == {"expired@x.com": "auth_required"}
    assert res.details["providers"]["google"]["error_type"] == "AllAccountsFailed"
    assert "traceback" not in res.details["providers"]["google"]
    assert not list(state_dir().glob("*calendar*.last_run"))


def test_calendar_event_carries_account_id():
    from ghostbrain.connectors.calendar._base import CalendarEvent

    ev = CalendarEvent(provider="google", account="a@x.com", event_id="1", title="t",
                       start="2026-09-27T10:00:00+00:00", end="2026-09-27T11:00:00+00:00",
                       is_all_day=False).to_event()
    assert ev["metadata"]["accountId"] == "a@x.com"


def test_recorder_google_source_uses_registry_contexts(v):
    from ghostbrain.recorder.sources import select_sources

    write_accounts(v, [
        {"connector": "calendar_google", "id": "a@agencyx.com", "context": "agencyx"},
        {"connector": "calendar_google", "id": "unassigned@x.com"},
    ])
    sources, _ = select_sources({}, {}, platform="win32")
    assert [s.id for s in sources] == ["google"]
    assert sources[0]._accounts == {"a@agencyx.com": "agencyx"}


# --------------------------------------------------------------------- slack

def test_slack_workspaces_from_registry(v):
    from ghostbrain.connectors.slack import runner

    write_accounts(v, [
        {"connector": "slack", "id": "agencyx", "context": "agencyx", "options": {"mode": "full"}},
        {"connector": "slack", "id": "newco"},
    ])
    assert runner.workspaces_config() == {"agencyx": {"mode": "full"}, "newco": {}}


def test_slack_workspace_without_context_is_fetched():
    from ghostbrain.connectors.slack.connector import _parse_workspaces

    [ws] = list(_parse_workspaces({"workspaces": {"newco": {}}}))
    assert ws.slug == "newco" and ws.context is None


def test_slack_one_broken_workspace(tmp_path, monkeypatch):
    from ghostbrain.connectors.slack.auth import SlackAuthError
    from ghostbrain.connectors.slack.connector import SlackConnector

    c = SlackConnector(config={"workspaces": {"good": {}, "revoked": {}}},
                       queue_dir=tmp_path / "q", state_dir=tmp_path / "s")

    def fake(ws):
        if ws.slug == "revoked":
            raise SlackAuthError("token_revoked")
        return [{"id": "slack:1", "metadata": {"workspace_slug": ws.slug, "accountId": ws.slug}}]

    monkeypatch.setattr(c, "_fetch_workspace", fake)
    assert [e["metadata"]["accountId"] for e in c.fetch(EPOCH)] == ["good"]
    assert accounts_health.health_for("slack", "revoked")["status"] == "auth_required"


# ----------------------------------------------------------------- atlassian

def test_atlassian_per_site_email_and_token_file(v, monkeypatch):
    from ghostbrain.connectors.atlassian import _base

    write_accounts(v, [
        {"connector": "jira", "id": "agencyx.atlassian.net", "options": {"email": "me@agencyx.com"}},
        {"connector": "confluence", "id": "agencyy.atlassian.net", "options": {"email": "me@agencyy.com"}},
    ])
    monkeypatch.setenv("ATLASSIAN_EMAIL", "legacy@old.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN", "legacy-global")
    _base.save_token("agencyx.atlassian.net", "x-token")
    assert _base.token_path("agencyx.atlassian.net").stat().st_mode & 0o777 == 0o600
    assert _base.auth_for_site("agencyx.atlassian.net") == ("me@agencyx.com", "x-token")
    assert _base.auth_for_site("agencyy.atlassian.net") == ("me@agencyy.com", "legacy-global")
    monkeypatch.setenv("ATLASSIAN_TOKEN_AGENCYX", "env-site")
    assert _base.auth_for_site("agencyx.atlassian.net")[1] == "env-site"
    assert _base.auth_for_site("other.atlassian.net") == ("legacy@old.com", "legacy-global")


def test_atlassian_auth_errors_without_email(v, monkeypatch):
    from ghostbrain.connectors.atlassian import _base

    write_accounts(v, [])
    monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
    with pytest.raises(_base.AtlassianAuthError):
        _base.auth_for_site("nobody.atlassian.net")


def test_jira_and_confluence_sites_from_registry(v):
    from ghostbrain.connectors.confluence import runner as conf_runner
    from ghostbrain.connectors.jira import runner as jira_runner

    write_accounts(v, [
        {"connector": "jira", "id": "a.atlassian.net"},
        {"connector": "confluence", "id": "b.atlassian.net"},
    ])
    assert jira_runner.sites() == ["a.atlassian.net"]
    assert conf_runner.sites() == ["b.atlassian.net"]


def test_jira_one_broken_site(tmp_path, monkeypatch):
    from ghostbrain.connectors.atlassian._base import AtlassianAuthError
    from ghostbrain.connectors.jira import JiraConnector

    c = JiraConnector(config={"sites": ["good.atlassian.net", "bad.atlassian.net"]},
                      queue_dir=tmp_path / "q", state_dir=tmp_path / "s")

    def fake(host, since):
        if host == "bad.atlassian.net":
            raise AtlassianAuthError("401")
        return iter([{"id": "jira:good:X-1", "metadata": {"site": host, "accountId": host}}])

    monkeypatch.setattr(c, "_fetch_site", fake)
    assert len(c.fetch(EPOCH)) == 1
    assert accounts_health.health_for("jira", "bad.atlassian.net")["status"] == "auth_required"


# -------------------------------------------------------------------- github

_GH_PR = {
    "number": 42, "title": "feat", "body": "", "url": "https://github.com/acme/x/pull/42",
    "state": "OPEN", "isDraft": False, "repository": {"nameWithOwner": "acme/x"},
    "author": {"login": "nikrich"}, "labels": [], "createdAt": "2026-09-20T08:00:00Z",
    "updatedAt": "2026-09-27T10:00:00Z",
}


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def test_github_runs_each_login_with_its_own_token(tmp_path, monkeypatch):
    import json

    from ghostbrain.connectors.github import GitHubConnector

    c = GitHubConnector(config={"orgs": ["acme"], "accounts": ["alice", "broken", "bob"]},
                        queue_dir=tmp_path / "q", state_dir=tmp_path / "s", gh_binary="/fake/gh")
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(args, *, timeout_s, env=None):
        token = (env or {}).get("GH_TOKEN")
        calls.append((args, token))
        if args[:2] == ["auth", "token"]:
            user = args[args.index("--user") + 1]
            return _Proc("", 1, "no token") if user == "broken" else _Proc(f"tok-{user}\n")
        if args[:2] == ["search", "prs"] and "--author=@me" in args:
            return _Proc(json.dumps([_GH_PR]))  # same PR visible to both logins
        return _Proc("[]")

    monkeypatch.setattr(c, "_run_gh", fake_run)
    events = c.fetch(EPOCH)
    assert len(events) == 1                                   # de-duplicated across logins
    assert events[0]["metadata"]["accountId"] == "alice"      # first account wins
    assert not any(a[:2] == ["auth", "switch"] for a, _ in calls)
    search_tokens = {t for a, t in calls if a[0] == "search"}
    assert search_tokens == {"tok-alice", "tok-bob"}
    assert accounts_health.health_for("github", "broken")["status"] == "auth_required"


def test_github_search_auth_failure_marks_account_auth_required(tmp_path, monkeypatch):
    """`gh auth token` can succeed while the token is already revoked; the
    failure only shows up when `gh search` runs. That must not be recorded
    as a quiet `ok` — it must mark the account `auth_required`, and the
    other (healthy) login's events must still come back."""
    import json

    from ghostbrain.connectors.github import GitHubConnector

    c = GitHubConnector(config={"orgs": ["acme"], "accounts": ["alice", "bob"]},
                        queue_dir=tmp_path / "q", state_dir=tmp_path / "s", gh_binary="/fake/gh")

    def fake_run(args, *, timeout_s, env=None):
        token = (env or {}).get("GH_TOKEN")
        if args[:2] == ["auth", "token"]:
            user = args[args.index("--user") + 1]
            return _Proc(f"tok-{user}\n")
        if args[0] == "search":
            if token == "tok-alice":
                return _Proc("", 1, "HTTP 401: Bad credentials")
            if args[:2] == ["search", "prs"] and "--author=@me" in args:
                return _Proc(json.dumps([_GH_PR]))
            return _Proc("[]")
        return _Proc("[]")

    monkeypatch.setattr(c, "_run_gh", fake_run)
    events = c.fetch(EPOCH)
    assert len(events) == 1
    assert events[0]["metadata"]["accountId"] == "bob"
    assert accounts_health.health_for("github", "alice")["status"] == "auth_required"
    assert accounts_health.health_for("github", "bob")["status"] == "ok"


def test_github_token_lookup_strips_ambient_token_env_vars(tmp_path, monkeypatch):
    """An ambient GH_TOKEN/GITHUB_TOKEN in the parent env must not leak into
    the `gh auth token --user <login>` call — otherwise gh returns that
    ambient token for every login, defeating per-login isolation. It must
    still end up in the search calls' env, as the per-login token."""
    from ghostbrain.connectors.github import GitHubConnector

    monkeypatch.setenv("GH_TOKEN", "ambient-gh")
    monkeypatch.setenv("GITHUB_TOKEN", "ambient-github")

    c = GitHubConnector(config={"orgs": ["acme"], "accounts": ["alice"]},
                        queue_dir=tmp_path / "q", state_dir=tmp_path / "s", gh_binary="/fake/gh")
    envs: list[tuple[list[str], dict]] = []

    def fake_run(args, *, timeout_s, env=None):
        envs.append((args, dict(env or {})))
        if args[:2] == ["auth", "token"]:
            return _Proc("tok-alice\n")
        return _Proc("[]")

    monkeypatch.setattr(c, "_run_gh", fake_run)
    c.fetch(EPOCH)

    auth_env = next(e for a, e in envs if a[:2] == ["auth", "token"])
    assert "GH_TOKEN" not in auth_env
    assert "GITHUB_TOKEN" not in auth_env

    search_env = next(e for a, e in envs if a[0] == "search")
    assert search_env["GH_TOKEN"] == "tok-alice"


def test_github_runner_uses_registry_logins(v, tmp_path, monkeypatch):
    from ghostbrain.connectors.github import runner

    write_accounts(v, [{"connector": "github", "id": "nikrich"}])
    monkeypatch.setattr("shutil.which", lambda name: "/fake/gh")
    c = runner._build({"github": {"orgs": {"acme": "personal"}}}, tmp_path / "q", tmp_path / "s")
    assert c.accounts == ["nikrich"] and c.orgs == ["acme"]
