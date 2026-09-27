"""accounts.yaml is seeded once from legacy routing.yaml blocks."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain import accounts

LEGACY = """\
contexts: [personal, agencyx, agencyy]
gmail:
  accounts:
    me@gmail.com:
      monitored_labels: [work]
      unread_lookback_hours: 48
    other@gmail.com: {}
  denylist_domains: ['*.spam.com']
calendar:
  google:
    accounts:
      me@agencyx.com: agencyx
    calendars_per_account:
      me@agencyx.com: [primary, team@group.calendar.google.com]
  macos:
    accounts:
      Work: agencyx
slack:
  workspaces:
    agencyx:
      context: agencyx
      mode: full
      allowed_channels: [general]
    placeholder:
      context: needs_review
    legacy: agencyy
jira:
  sites:
    agencyx.atlassian.net: agencyx
    agencyy.atlassian.net: needs_review
confluence:
  spaces:
    DOCS: agencyx
"""


@pytest.fixture
def v(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(LEGACY, encoding="utf-8")
    return root


def _entries(root: Path) -> list[tuple]:
    raw = yaml.safe_load((root / "90-meta" / "accounts.yaml").read_text(encoding="utf-8"))
    return [(e["connector"], e["id"], e.get("context"), e.get("options", {})) for e in raw["accounts"]]


def test_seed_writes_every_legacy_account(v):
    accounts.list_accounts()
    assert _entries(v) == [
        ("gmail", "me@gmail.com", None, {"monitored_labels": ["work"], "unread_lookback_hours": 48}),
        ("gmail", "other@gmail.com", None, {}),
        ("calendar_google", "me@agencyx.com", "agencyx",
         {"calendars": ["primary", "team@group.calendar.google.com"]}),
        ("slack", "agencyx", "agencyx", {"mode": "full", "allowed_channels": ["general"]}),
        ("slack", "placeholder", None, {}),
        ("slack", "legacy", "agencyy", {}),
        ("jira", "agencyx.atlassian.net", "agencyx", {}),
        ("jira", "agencyy.atlassian.net", None, {}),
        # confluence.spaces is non-empty and confluence.sites is absent -> jira sites
        ("confluence", "agencyx.atlassian.net", "agencyx", {}),
        ("confluence", "agencyy.atlassian.net", None, {}),
    ]


def test_seed_skips_confluence_without_spaces(v):
    text = LEGACY.replace("confluence:\n  spaces:\n    DOCS: agencyx\n", "")
    (v / "90-meta" / "routing.yaml").write_text(text, encoding="utf-8")
    assert accounts.list_accounts("confluence") == []


def test_seed_runs_once(v):
    accounts.list_accounts()
    (v / "90-meta" / "routing.yaml").write_text(
        LEGACY.replace("other@gmail.com: {}", "other@gmail.com: {}\n    third@gmail.com: {}"),
        encoding="utf-8",
    )
    assert [a.id for a in accounts.list_accounts("gmail")] == ["me@gmail.com", "other@gmail.com"]


def test_seed_live_github_and_microsoft(v, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_ACCOUNTS_LIVE_SEED", "1")
    monkeypatch.setattr(accounts, "gh_logins", lambda host="github.com": ["nikrich", "work-bot"])
    monkeypatch.setattr(accounts, "_msal_usernames", lambda routing: ["me@agencyy.com"])
    got = [(a.connector, a.id) for a in accounts.list_accounts() if a.connector in ("github", "microsoft")]
    assert got == [("github", "nikrich"), ("github", "work-bot"), ("microsoft", "me@agencyy.com")]


def test_seed_live_failures_are_non_fatal(v, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_ACCOUNTS_LIVE_SEED", "1")

    def boom(*a, **k):
        raise RuntimeError("keychain locked")

    monkeypatch.setattr(accounts, "gh_logins", boom)
    monkeypatch.setattr(accounts, "_msal_usernames", boom)
    assert len(accounts.list_accounts("gmail")) == 2


def test_gh_logins_parses_every_account(monkeypatch):
    class P:
        returncode = 1  # gh exits non-zero when any account has a problem
        stdout = ""
        stderr = (
            "github.com\n"
            "  ✓ Logged in to github.com account nikrich (keyring)\n"
            "  - Active account: true\n"
            "  X Failed to log in to github.com account old-bot (keyring)\n"
        )

    monkeypatch.setattr(accounts.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(accounts.subprocess, "run", lambda *a, **k: P())
    assert accounts.gh_logins() == ["nikrich", "old-bot"]


def test_gh_logins_without_gh(monkeypatch):
    monkeypatch.setattr(accounts.shutil, "which", lambda name: None)
    assert accounts.gh_logins() == []
