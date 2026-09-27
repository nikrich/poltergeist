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
