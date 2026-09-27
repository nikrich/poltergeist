# Multi-Account Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every account-bearing connector (Gmail, Google Calendar, Slack, Jira, Confluence, GitHub, Microsoft) supports any number of accounts, each optionally mapped to a context that its captures route to, with one broken account never stopping the others.

**Architecture:** A new registry module `ghostbrain/accounts.py` owns `<vault>/90-meta/accounts.yaml` (seeded once from the legacy `routing.yaml` blocks). Connectors read their accounts from it, tag every event with `metadata.accountId`, and loop accounts through `ghostbrain/accounts_health.py:for_each_account`, which isolates failures and records per-account health in `<state>/accounts_health.json`. The router gains one generic account → context rule after the specific rules and before the LLM. The existing in-app connect flows write the registry instead of `routing.yaml`, and the connectors API exposes the account list with health.

**Tech Stack:** Python 3.11+ (PyYAML, FastAPI, pydantic, msal, subprocess `gh`), pytest; TypeScript types only on the desktop side.

**Spec:** `docs/superpowers/specs/2026-09-27-multi-account-connectors-design.md` (read §4 "Existing in-app connect flows and other readers" — it was added during planning).

## Global Constraints

- Work in the worktree `/Users/jannik/development/nikrich/ghost-brain-multi-account` on branch `feat/multi-account-connectors`. **Every shell command starts with `cd /Users/jannik/development/nikrich/ghost-brain-multi-account &&`** and you verify `git branch --show-current` prints `feat/multi-account-connectors` before your first commit. Never work in `/Users/jannik/development/nikrich/ghost-brain` (a stale, dirty checkout).
- Python tests: `.venv/bin/python -m pytest <path> -q -p no:cacheprovider`. The venv already exists (created with `uv sync --extra dev --extra api`). A repo-root `conftest.py` sandboxes HOME / `GHOSTBRAIN_STATE_DIR` / `VAULT_PATH` (= `<tmp_path>/vault`) for every test.
- **Pre-existing failures (baseline, not yours):** `tests/test_recorder_wasapi_io.py` (collection error: numpy), and 22 failures in `test_agent_stream.py`(1), `test_calendar.py`(1), `test_joplin_connector.py`(2), `test_mcp_integration.py`(1), `test_mcp_tools.py`(2), `test_recorder_api_platform_guard.py`(1), `test_recorder_audio_backend.py`(7), `test_recorder_platform_guard.py`(2), `test_semantic.py`(4), `test_weekly_digest.py`(1). Full-suite command: `.venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_recorder_wasapi_io.py`. Your task is green when it adds no failures beyond this list.
- Ruff: `.venv/bin/python -m ruff check <files you touched>` must be clean for new code (pre-existing findings in untouched lines are not yours).
- Account connector names (exact strings): `gmail`, `calendar_google`, `slack`, `jira`, `confluence`, `github`, `microsoft`.
- Health keys use the **fetching connector's name** (the API/scheduler id): `gmail`, `calendar`, `slack`, `jira`, `confluence`, `github`, `outlook_mail`, `teams_chat`, `teams_meetings`, formatted `"<connector>:<account id lower-cased>"`.
- Health statuses (exact strings): `ok`, `auth_required`, `error`.
- `RoutingDecision.method` for the new rule is exactly `"account"`, confidence `0.95`.
- `needs_review` is never a valid account context; seeding and the connect flows treat it as unassigned.
- Secrets never go into `accounts.yaml`.
- Tests never call a real `gh`, Google, Slack, Atlassian, or Microsoft endpoint. The root `conftest.py` sets `GHOSTBRAIN_ACCOUNTS_LIVE_SEED=0` (Task 1) so seeding never shells out to `gh` or opens the MSAL keychain cache during tests.
- Commits: conventional commits, one per task (more is fine), each ending with:
  ```
  Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
  ```

## Review Focus

1. **A user who configured accounts in `routing.yaml` before upgrading** — the first read seeds `accounts.yaml` with every Gmail/Calendar/Slack/Jira/Confluence account and its context, and routing is unchanged afterwards. Test: Task 1 `test_seed_*` + Task 3 router tests + Task 12 Step 4 migration smoke test.
2. **The worker process reads the registry while the API writes it** — a reader never sees a half-written file. Test: Task 1 `test_concurrent_upserts_keep_every_account`.
3. **An account whose context was removed from `contexts:`** — keeps syncing, routes via LLM, never crashes the router. Test: Task 1 `test_context_for_ignores_unknown_context`, Task 3 `test_unassigned_or_stale_account_falls_through_to_llm`.
4. **Reconnecting an already-connected account from the app** — keeps its context. Test: Task 10 `test_google_success_keeps_existing_context`.
5. **A malformed `accounts.yaml` (hand-edit typo)** — no crash, nothing routed from `routing.yaml` blocks, connectors report "not configured". Test: Task 1 `test_malformed_file_yields_no_accounts_and_no_reseed`.

## File Structure

Created:
- `ghostbrain/accounts.py` — `Account`, registry read/write/lookup, seeding, `SOURCE_TO_ACCOUNT_CONNECTOR`, `account_connector_for_event`, `gh_logins`.
- `ghostbrain/accounts_health.py` — health file, `for_each_account`, `last_run_summary`.
- `ghostbrain/connectors/microsoft/graph/multi.py` — per-account Graph fetch helper shared by the three Microsoft connectors.
- Tests: `tests/test_accounts.py`, `tests/test_accounts_seed.py`, `tests/test_accounts_health.py`, `tests/test_router_accounts.py`, `tests/test_multi_account_connectors.py`, `tests/test_microsoft_multi_account.py`, `tests/api/auth/test_providers_registry.py`, `ghostbrain/api/tests/test_connectors_accounts.py`.

Modified (by task): `conftest.py` (1); `ghostbrain/connectors/_runner.py` (2); `ghostbrain/worker/router.py` (3); Gmail package (4); Calendar package + `ghostbrain/recorder/sources/__init__.py` (5); Slack package (6); `atlassian/_base.py`, Jira, Confluence packages, `api/repo/import_atlassian.py`, `api/repo/connector_probe.py` (7); GitHub package (8); Microsoft package (9); `api/auth/providers/*.py`, `api/auth/disconnect.py` (10); `api/repo/connectors.py`, `api/models/connector.py`, `doctor/checks_connectors.py`, `desktop/src/shared/api-types.ts` (11); `bootstrap.py`, docs (12).

---

### Task 1: Account registry and seeding

**Files:**
- Create: `ghostbrain/accounts.py`
- Modify: `conftest.py` (repo root)
- Test: `tests/test_accounts.py`, `tests/test_accounts_seed.py`

**Interfaces:**
- Consumes: `ghostbrain.routing_config.contexts(root: Path | None) -> tuple[str, ...]`; `ghostbrain.paths.vault_path()`; `ghostbrain.connectors.microsoft.graph.auth.cache_location()` and `_build_app(config)` (existing).
- Produces:
  - `ACCOUNT_CONNECTORS: tuple[str, ...]`
  - `SOURCE_TO_ACCOUNT_CONNECTOR: dict[str, str]`
  - `@dataclass(frozen=True) class Account(connector: str, id: str, context: str | None = None, enabled: bool = True, options: dict = {})` with property `key -> tuple[str, str]`
  - `accounts_path(root: Path | None = None) -> Path`
  - `list_accounts(connector: str | None = None, *, root: Path | None = None, include_disabled: bool = False) -> list[Account]`
  - `get_account(connector: str | None, account_id: str | None, *, root=None) -> Account | None`
  - `context_for(connector: str | None, account_id: str | None, *, root=None) -> str | None`
  - `account_connector_for_event(event: dict) -> str | None`
  - `upsert_account(acc: Account, *, root=None) -> Account` (raises `ValueError` on unknown connector, empty id, or unknown context)
  - `ensure_account(connector: str, account_id: str, *, options: dict | None = None, root=None) -> Account`
  - `remove_account(connector: str, account_id: str, *, root=None) -> bool`
  - `gh_logins(host: str = "github.com") -> list[str]`

- [ ] **Step 1: Make seeding hermetic in tests**

In the repo-root `conftest.py`, inside `_isolate_user_state`, after the `VAULT_PATH` line add:

```python
    # accounts.yaml seeding would otherwise shell out to `gh` and open the
    # MSAL keychain cache; tests opt back in explicitly.
    monkeypatch.setenv("GHOSTBRAIN_ACCOUNTS_LIVE_SEED", "0")
```

- [ ] **Step 2: Write the failing registry tests**

Create `tests/test_accounts.py`:

```python
"""accounts.yaml registry: read/write/lookup semantics."""
from __future__ import annotations

import threading
from pathlib import Path

import pytest
import yaml

from ghostbrain import accounts


@pytest.fixture
def v(tmp_path: Path) -> Path:
    """Vault with three contexts and no accounts.yaml yet (VAULT_PATH is
    already <tmp_path>/vault via the root conftest)."""
    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text(
        "contexts:\n  - personal\n  - agencyx\n  - agencyy\n", encoding="utf-8"
    )
    return root


def _write_accounts(root: Path, entries: list[dict]) -> None:
    (root / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": entries}), encoding="utf-8"
    )


def test_list_filters_by_connector_and_enabled(v):
    _write_accounts(v, [
        {"connector": "gmail", "id": "a@x.com", "context": "personal"},
        {"connector": "gmail", "id": "b@x.com", "enabled": False},
        {"connector": "slack", "id": "agencyx", "context": "agencyx"},
    ])
    assert [a.id for a in accounts.list_accounts("gmail")] == ["a@x.com"]
    assert [a.id for a in accounts.list_accounts("gmail", include_disabled=True)] == ["a@x.com", "b@x.com"]
    assert {a.connector for a in accounts.list_accounts()} == {"gmail", "slack"}


def test_lookup_is_case_insensitive(v):
    _write_accounts(v, [{"connector": "gmail", "id": "Me@X.com", "context": "personal"}])
    acc = accounts.get_account("gmail", "me@x.com")
    assert acc is not None and acc.id == "Me@X.com"
    assert accounts.context_for("gmail", "ME@X.COM") == "personal"


def test_context_for_ignores_unknown_context(v):
    _write_accounts(v, [{"connector": "gmail", "id": "a@x.com", "context": "archived-agency"}])
    assert accounts.get_account("gmail", "a@x.com").context == "archived-agency"
    assert accounts.context_for("gmail", "a@x.com") is None


def test_context_for_none_inputs(v):
    _write_accounts(v, [])
    assert accounts.context_for(None, "a@x.com") is None
    assert accounts.context_for("gmail", None) is None


def test_unknown_connector_and_duplicates_are_ignored(v, caplog):
    _write_accounts(v, [
        {"connector": "myspace", "id": "tom"},
        {"connector": "gmail", "id": "a@x.com", "context": "personal"},
        {"connector": "gmail", "id": "A@x.com", "context": "agencyx"},
        {"connector": "gmail"},
    ])
    got = accounts.list_accounts()
    assert [(a.connector, a.id, a.context) for a in got] == [("gmail", "a@x.com", "personal")]


def test_malformed_file_yields_no_accounts_and_no_reseed(v):
    (v / "90-meta" / "routing.yaml").write_text(
        "contexts: [personal]\ngmail:\n  accounts:\n    legacy@x.com: {}\n", encoding="utf-8"
    )
    (v / "90-meta" / "accounts.yaml").write_text("accounts: [unclosed\n", encoding="utf-8")
    assert accounts.list_accounts() == []
    # The broken file is left for the user to fix, never overwritten by a re-seed.
    assert "unclosed" in (v / "90-meta" / "accounts.yaml").read_text(encoding="utf-8")


def test_upsert_adds_then_replaces_in_place(v):
    _write_accounts(v, [
        {"connector": "gmail", "id": "a@x.com"},
        {"connector": "slack", "id": "agencyx"},
    ])
    accounts.upsert_account(accounts.Account("gmail", "a@x.com", "personal", True, {"unread_lookback_hours": 48}))
    accounts.upsert_account(accounts.Account("github", "nikrich"))
    got = accounts.list_accounts()
    assert [(a.connector, a.id) for a in got] == [("gmail", "a@x.com"), ("slack", "agencyx"), ("github", "nikrich")]
    assert got[0].context == "personal"
    assert got[0].options == {"unread_lookback_hours": 48}
    raw = yaml.safe_load((v / "90-meta" / "accounts.yaml").read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["accounts"][2] == {"connector": "github", "id": "nikrich"}


@pytest.mark.parametrize("acc", [
    accounts.Account("myspace", "tom"),
    accounts.Account("gmail", "  "),
    accounts.Account("gmail", "a@x.com", "needs_review"),
    accounts.Account("gmail", "a@x.com", "not-a-context"),
])
def test_upsert_rejects_invalid(v, acc):
    _write_accounts(v, [])
    with pytest.raises(ValueError):
        accounts.upsert_account(acc)


def test_ensure_account_keeps_context_and_merges_options(v):
    _write_accounts(v, [{"connector": "jira", "id": "agencyx.atlassian.net", "context": "agencyx",
                         "options": {"email": "old@x.com", "keep": 1}}])
    acc = accounts.ensure_account("jira", "AGENCYX.atlassian.net", options={"email": "new@x.com"})
    assert acc.context == "agencyx"
    assert acc.options == {"email": "new@x.com", "keep": 1}
    fresh = accounts.ensure_account("gmail", "new@x.com")
    assert fresh.context is None and fresh.enabled


def test_remove_account(v):
    _write_accounts(v, [{"connector": "gmail", "id": "a@x.com"}])
    assert accounts.remove_account("gmail", "A@X.COM") is True
    assert accounts.remove_account("gmail", "a@x.com") is False
    assert accounts.list_accounts() == []


def test_concurrent_upserts_keep_every_account(v):
    _write_accounts(v, [])
    errors: list[BaseException] = []

    def add(i: int) -> None:
        try:
            accounts.upsert_account(accounts.Account("gmail", f"user{i}@x.com"))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=add, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(accounts.list_accounts("gmail")) == 20


def test_account_connector_for_event():
    f = accounts.account_connector_for_event
    assert f({"source": "gmail"}) == "gmail"
    assert f({"source": "calendar", "metadata": {"provider": "google"}}) == "calendar_google"
    assert f({"source": "calendar", "metadata": {"provider": "macos"}}) is None
    assert f({"source": "teams_chat"}) == "microsoft"
    assert f({"source": "claude_code"}) is None


def test_no_vault_meta_dir_returns_empty_without_writing(tmp_path):
    # VAULT_PATH points at <tmp_path>/vault, which doesn't exist here.
    assert accounts.list_accounts() == []
    assert not (tmp_path / "vault" / "90-meta" / "accounts.yaml").exists()
```

- [ ] **Step 3: Write the failing seeding tests**

Create `tests/test_accounts_seed.py`:

```python
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
```

- [ ] **Step 4: Run both test files to verify they fail**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_accounts.py tests/test_accounts_seed.py -q -p no:cacheprovider`
Expected: collection ERROR — `ImportError: cannot import name 'accounts' from 'ghostbrain'`.

- [ ] **Step 5: Implement `ghostbrain/accounts.py`**

```python
"""Per-account connector registry — ``<vault>/90-meta/accounts.yaml``.

One list of connected accounts (a Gmail address, a Slack workspace, an
Atlassian site, a gh login, a Microsoft username), each optionally mapped to a
context. This module is the only reader and writer of that file: connectors
read their accounts here, and the router maps ``metadata.accountId`` to a
context here.

The file is seeded once from the legacy per-account blocks in routing.yaml
(``gmail.accounts``, ``calendar.google.accounts``, ``slack.workspaces``,
``jira.sites``, ``confluence.sites``) plus live ``gh`` / MSAL logins, the
first time it is read and does not exist. After that those routing.yaml
blocks are ignored. Secrets never live here.
"""
from __future__ import annotations

import contextlib
import dataclasses
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Iterator

import yaml

from ghostbrain import routing_config
from ghostbrain.paths import vault_path

try:
    import fcntl
except ImportError:  # Windows: in-process lock only
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger("ghostbrain.accounts")

ACCOUNT_CONNECTORS: tuple[str, ...] = (
    "gmail", "calendar_google", "slack", "jira", "confluence", "github", "microsoft",
)

# Event source / connector id -> account connector. Calendar events from the
# macos provider have no account connector (see account_connector_for_event).
SOURCE_TO_ACCOUNT_CONNECTOR: dict[str, str] = {
    "gmail": "gmail",
    "calendar": "calendar_google",
    "slack": "slack",
    "jira": "jira",
    "confluence": "confluence",
    "github": "github",
    "outlook_mail": "microsoft",
    "teams_chat": "microsoft",
    "teams_meetings": "microsoft",
}

# Placeholder contexts older connect flows wrote; never a real assignment.
_UNASSIGNED = frozenset({"needs_review"})

_thread_lock = threading.RLock()


@dataclasses.dataclass(frozen=True)
class Account:
    connector: str
    id: str
    context: str | None = None
    enabled: bool = True
    options: dict = dataclasses.field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str]:
        return (self.connector, self.id.lower())


def accounts_path(root: Path | None = None) -> Path:
    return (root or vault_path()) / "90-meta" / "accounts.yaml"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_accounts(
    connector: str | None = None,
    *,
    root: Path | None = None,
    include_disabled: bool = False,
) -> list[Account]:
    _ensure_seeded(root)
    return [
        a for a in _read(accounts_path(root))
        if (connector is None or a.connector == connector)
        and (include_disabled or a.enabled)
    ]


def get_account(
    connector: str | None, account_id: str | None, *, root: Path | None = None,
) -> Account | None:
    if not connector or not account_id:
        return None
    key = (connector, str(account_id).lower())
    for a in list_accounts(connector, root=root, include_disabled=True):
        if a.key == key:
            return a
    return None


def context_for(
    connector: str | None, account_id: str | None, *, root: Path | None = None,
) -> str | None:
    """The account's context, or None when unassigned, unknown, or the
    context is no longer in routing.yaml's ``contexts:`` list."""
    acc = get_account(connector, account_id, root=root)
    if acc is None or not acc.context:
        return None
    if acc.context not in routing_config.contexts(root):
        return None
    return acc.context


def account_connector_for_event(event: dict) -> str | None:
    source = event.get("source") or ""
    if source == "calendar":
        provider = (event.get("metadata") or {}).get("provider")
        return "calendar_google" if provider == "google" else None
    return SOURCE_TO_ACCOUNT_CONNECTOR.get(source)


def upsert_account(acc: Account, *, root: Path | None = None) -> Account:
    _validate(acc, root)
    _ensure_seeded(root)
    path = accounts_path(root)
    with _locked(root):
        current = _read(path)
        out: list[Account] = []
        replaced = False
        for a in current:
            if a.key == acc.key:
                out.append(acc)
                replaced = True
            else:
                out.append(a)
        if not replaced:
            out.append(acc)
        _write(path, out)
    return acc


def ensure_account(
    connector: str,
    account_id: str,
    *,
    options: dict | None = None,
    root: Path | None = None,
) -> Account:
    """Add the account unassigned if absent; otherwise merge ``options`` into
    it, keeping its context and enabled flag. Used by auth flows."""
    existing = get_account(connector, account_id, root=root)
    if existing is None:
        return upsert_account(
            Account(connector, account_id.strip(), None, True, dict(options or {})),
            root=root,
        )
    if options:
        merged = {**existing.options, **options}
        if merged != existing.options:
            return upsert_account(dataclasses.replace(existing, options=merged), root=root)
    return existing


def remove_account(connector: str, account_id: str, *, root: Path | None = None) -> bool:
    _ensure_seeded(root)
    path = accounts_path(root)
    key = (connector, str(account_id).lower())
    with _locked(root):
        current = _read(path)
        kept = [a for a in current if a.key != key]
        if len(kept) == len(current):
            return False
        _write(path, kept)
    return True


def gh_logins(host: str = "github.com") -> list[str]:
    """Every account ``gh`` knows for ``host`` (gh supports several logins
    per host). Empty when gh is missing or fails."""
    gh = shutil.which("gh")
    if gh is None:
        return []
    try:
        r = subprocess.run(
            [gh, "auth", "status", "--hostname", host],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("gh auth status failed: %s", e)
        return []
    found = re.findall(r"account (\S+)", (r.stdout or "") + (r.stderr or ""))
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _locked(root: Path | None) -> Iterator[None]:
    """Serialise writers across threads (scheduler + API share a process) and,
    where fcntl exists, across processes (auth CLIs, the worker)."""
    meta = accounts_path(root).parent
    with _thread_lock:
        if fcntl is None or not meta.exists():
            yield
            return
        with open(meta / ".accounts.lock", "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)


def _read(path: Path) -> list[Account]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, yaml.YAMLError) as e:
        log.warning("could not read %s (%s); no accounts loaded", path, e)
        return []
    return _parse({"accounts": []} if data is None else data, path)


def _parse(data: object, source: Path) -> list[Account]:
    entries = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        log.warning("%s is malformed (no `accounts:` list); no accounts loaded", source)
        return []
    out: list[Account] = []
    seen: set[tuple[str, str]] = set()
    for i, raw in enumerate(entries):
        if not isinstance(raw, dict):
            log.warning("%s: ignoring entry %d (not a mapping)", source, i)
            continue
        connector = str(raw.get("connector") or "").strip()
        acc_id = str(raw.get("id") or "").strip()
        if connector not in ACCOUNT_CONNECTORS or not acc_id:
            log.warning("%s: ignoring entry %d (connector=%r id=%r)", source, i, connector, acc_id)
            continue
        ctx = raw.get("context")
        ctx = ctx.strip() if isinstance(ctx, str) and ctx.strip() else None
        options = raw.get("options")
        acc = Account(
            connector=connector,
            id=acc_id,
            context=ctx,
            enabled=bool(raw.get("enabled", True)),
            options=dict(options) if isinstance(options, dict) else {},
        )
        if acc.key in seen:
            log.warning("%s: ignoring duplicate %s account %s", source, connector, acc_id)
            continue
        seen.add(acc.key)
        out.append(acc)
    return out


def _to_dict(acc: Account) -> dict:
    d: dict = {"connector": acc.connector, "id": acc.id}
    if acc.context:
        d["context"] = acc.context
    if not acc.enabled:
        d["enabled"] = False
    if acc.options:
        d["options"] = dict(acc.options)
    return d


def _write(path: Path, accs: list[Account]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"version": 1, "accounts": [_to_dict(a) for a in accs]}
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".accounts.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(
                "# Connected accounts per connector, each optionally mapped to a context.\n"
                "# Managed by Poltergeist (connect flows / Settings); safe to hand-edit.\n"
            )
            yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _validate(acc: Account, root: Path | None) -> None:
    if acc.connector not in ACCOUNT_CONNECTORS:
        raise ValueError(f"unknown account connector: {acc.connector!r}")
    if not acc.id or not acc.id.strip():
        raise ValueError("account id is required")
    if acc.context is not None and acc.context not in routing_config.contexts(root):
        raise ValueError(
            f"unknown context: {acc.context!r}; valid: {list(routing_config.contexts(root))}"
        )


# ---------------------------------------------------------------------------
# Seeding (once, from legacy routing.yaml blocks + live logins)
# ---------------------------------------------------------------------------


def _ensure_seeded(root: Path | None) -> None:
    path = accounts_path(root)
    if path.exists() or not path.parent.exists():
        return
    with _locked(root):
        if path.exists():
            return
        seeded = _seed(root)
        _write(path, seeded)
    log.info(
        "seeded %s with %d account(s) from routing.yaml; its per-account blocks "
        "(gmail.accounts, calendar.google.accounts, slack.workspaces, jira.sites, "
        "confluence.sites) are no longer read",
        path, len(seeded),
    )


def _seed(root: Path | None) -> list[Account]:
    routing = _load_routing(root)
    accs = _seed_from_routing(routing)
    if os.environ.get("GHOSTBRAIN_ACCOUNTS_LIVE_SEED", "1") != "0":
        try:
            accs += [Account("github", login) for login in gh_logins()]
        except Exception as e:  # noqa: BLE001
            log.warning("could not list gh logins while seeding: %s", e)
        try:
            accs += [Account("microsoft", u) for u in _msal_usernames(routing)]
        except Exception as e:  # noqa: BLE001
            log.warning("could not list Microsoft accounts while seeding: %s", e)
    out: list[Account] = []
    seen: set[tuple[str, str]] = set()
    for a in accs:
        if a.key not in seen:
            seen.add(a.key)
            out.append(a)
    return out


def _load_routing(root: Path | None) -> dict:
    f = (root or vault_path()) / "90-meta" / "routing.yaml"
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _ctx(value: object) -> str | None:
    if isinstance(value, str) and value.strip() and value.strip() not in _UNASSIGNED:
        return value.strip()
    return None


def _mapping(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return {str(v): None for v in value}
    return {}


def _seed_from_routing(routing: dict) -> list[Account]:
    out: list[Account] = []

    gmail = routing.get("gmail") or {}
    for email, cfg in _mapping(gmail.get("accounts")).items():
        out.append(Account("gmail", str(email), None, True, dict(cfg) if isinstance(cfg, dict) else {}))

    google = (routing.get("calendar") or {}).get("google") or {}
    calendars = google.get("calendars_per_account") or {}
    for email, ctx in _mapping(google.get("accounts")).items():
        opts = {"calendars": list(calendars[email])} if calendars.get(email) else {}
        out.append(Account("calendar_google", str(email), _ctx(ctx), True, opts))

    for slug, cfg in _mapping((routing.get("slack") or {}).get("workspaces")).items():
        cfg = dict(cfg) if isinstance(cfg, dict) else {"context": cfg}
        ctx = _ctx(cfg.pop("context", None))
        out.append(Account("slack", str(slug), ctx, True, cfg))

    jira_sites = _mapping((routing.get("jira") or {}).get("sites"))
    for host, ctx in jira_sites.items():
        out.append(Account("jira", str(host), _ctx(ctx)))

    confluence = routing.get("confluence") or {}
    conf_sites = _mapping(confluence.get("sites"))
    if not conf_sites and confluence.get("spaces"):
        conf_sites = jira_sites
    for host, ctx in conf_sites.items():
        out.append(Account("confluence", str(host), _ctx(ctx) or _ctx(jira_sites.get(host))))

    return out


def _msal_usernames(routing: dict) -> list[str]:
    from ghostbrain.connectors.microsoft.graph import auth as ms_auth

    if not ms_auth.cache_location().exists():
        return []
    app = ms_auth._build_app(routing.get("microsoft") or {})
    return [a["username"] for a in app.get_accounts() if a.get("username")]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_accounts.py tests/test_accounts_seed.py tests/test_no_hardcoded_contexts.py tests/test_conftest_isolation.py -q -p no:cacheprovider`
Expected: all PASS.

- [ ] **Step 7: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/accounts.py tests/test_accounts.py tests/test_accounts_seed.py conftest.py
git add ghostbrain/accounts.py tests/test_accounts.py tests/test_accounts_seed.py conftest.py
git commit -m "feat(accounts): accounts.yaml registry with one-time seeding from routing.yaml

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Per-account health and runner integration

**Files:**
- Create: `ghostbrain/accounts_health.py`
- Modify: `ghostbrain/connectors/_runner.py` (inside `run_connector`)
- Test: `tests/test_accounts_health.py`

**Interfaces:**
- Consumes: `ghostbrain.paths.state_dir()`.
- Produces:
  - `STATUS_OK = "ok"`, `STATUS_AUTH = "auth_required"`, `STATUS_ERROR = "error"`
  - `health_path() -> Path`
  - `load_health() -> dict[str, dict]`
  - `health_for(connector: str, account_id: str) -> dict | None` — `{"status", "checkedAt", "lastSuccessAt", "error"}`
  - `record(connector: str, account_id: str, status: str, error: str | None = None) -> None`
  - `for_each_account(connector: str, items: Iterable[T], fn: Callable[[T], Iterable[dict]], *, account_id: Callable[[T], str], auth_errors: tuple[type[BaseException], ...] = ()) -> list[dict]`
  - `clear_last_run(connector: str) -> None`, `last_run_summary(connector: str) -> dict[str, str]` (account id → status for the latest run)
  - `run_connector` returns `details={"accounts": {...}}` when accounts ran, and `ok=False, error_type="AllAccountsFailed"` when none succeeded.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accounts_health.py`:

```python
from __future__ import annotations

from pathlib import Path

from ghostbrain import accounts_health as ah


class FakeAuthError(RuntimeError):
    pass


def test_for_each_account_isolates_failures_and_records_health():
    def fetch(acc: str) -> list[dict]:
        if acc == "expired@x.com":
            raise FakeAuthError("refresh token rejected")
        if acc == "flaky@x.com":
            raise TimeoutError("read timed out")
        return [{"id": f"ev-{acc}"}]

    events = ah.for_each_account(
        "gmail", ["ok@x.com", "expired@x.com", "flaky@x.com"], fetch,
        account_id=lambda a: a, auth_errors=(FakeAuthError,),
    )
    assert events == [{"id": "ev-ok@x.com"}]
    assert ah.health_for("gmail", "ok@x.com")["status"] == "ok"
    assert ah.health_for("gmail", "OK@X.com")["lastSuccessAt"] is not None
    expired = ah.health_for("gmail", "expired@x.com")
    assert expired["status"] == "auth_required"
    assert "refresh token rejected" in expired["error"]
    assert expired["lastSuccessAt"] is None
    assert ah.health_for("gmail", "flaky@x.com")["status"] == "error"
    assert ah.last_run_summary("gmail") == {
        "ok@x.com": "ok", "expired@x.com": "auth_required", "flaky@x.com": "error",
    }


def test_last_success_survives_a_later_failure():
    ah.record("slack", "acme", ah.STATUS_OK)
    first = ah.health_for("slack", "acme")["lastSuccessAt"]
    ah.record("slack", "acme", ah.STATUS_ERROR, "boom")
    h = ah.health_for("slack", "acme")
    assert h["status"] == "error" and h["lastSuccessAt"] == first and h["error"] == "boom"


def test_unreadable_health_file_is_treated_as_empty():
    p = ah.health_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert ah.load_health() == {}
    ah.record("jira", "a.atlassian.net", ah.STATUS_OK)
    assert ah.health_for("jira", "a.atlassian.net")["status"] == "ok"


def test_run_connector_reports_accounts_and_all_failed(tmp_path: Path, monkeypatch):
    from ghostbrain.connectors import _runner

    class AllFail:
        def health_check(self) -> bool:
            return True

        def run(self) -> int:
            ah.for_each_account("gmail", ["a@x.com"], lambda a: 1 / 0, account_id=lambda a: a)
            return 0

    class OneOk:
        def health_check(self) -> bool:
            return True

        def run(self) -> int:
            ah.for_each_account("gmail", ["a@x.com"], lambda a: [{}], account_id=lambda a: a)
            return 1

    monkeypatch.setattr(_runner, "load_routing", lambda: {})
    bad = _runner.run_connector("gmail", build=lambda r, q, s: AllFail())
    assert bad.ok is False and bad.error_type == "AllAccountsFailed"
    assert bad.details["accounts"] == {"a@x.com": "error"}

    good = _runner.run_connector("gmail", build=lambda r, q, s: OneOk())
    assert good.ok is True and good.queued == 1
    assert good.details == {"accounts": {"a@x.com": "ok"}}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_accounts_health.py -q -p no:cacheprovider`
Expected: collection ERROR — `cannot import name 'accounts_health'`.

- [ ] **Step 3: Implement `ghostbrain/accounts_health.py`**

```python
"""Per-account connector health — ``<state>/accounts_health.json``.

Keyed ``"<connector>:<account id lower-cased>"`` where connector is the
fetching connector's name (gmail, calendar, outlook_mail, ...). Written by
``for_each_account``, read by the connectors API.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, TypeVar

from ghostbrain.paths import state_dir

log = logging.getLogger("ghostbrain.accounts_health")

STATUS_OK = "ok"
STATUS_AUTH = "auth_required"
STATUS_ERROR = "error"

T = TypeVar("T")

_lock = threading.Lock()
_last_run: dict[str, dict[str, str]] = {}


def health_path() -> Path:
    return state_dir() / "accounts_health.json"


def _key(connector: str, account_id: str) -> str:
    return f"{connector}:{account_id.lower()}"


def load_health() -> dict[str, dict]:
    try:
        data = json.loads(health_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("could not read %s (%s); treating as empty", health_path(), e)
        return {}
    return data if isinstance(data, dict) else {}


def health_for(connector: str, account_id: str) -> dict | None:
    return load_health().get(_key(connector, account_id))


def record(connector: str, account_id: str, status: str, error: str | None = None) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _lock:
        data = load_health()
        key = _key(connector, account_id)
        entry = dict(data.get(key) or {})
        entry["status"] = status
        entry["checkedAt"] = now
        entry["error"] = error
        if status == STATUS_OK:
            entry["lastSuccessAt"] = now
        entry.setdefault("lastSuccessAt", None)
        data[key] = entry
        _write(data)
    _last_run.setdefault(connector, {})[account_id] = status


def _write(data: dict) -> None:
    p = health_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".accounts_health.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, p)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def clear_last_run(connector: str) -> None:
    _last_run.pop(connector, None)


def last_run_summary(connector: str) -> dict[str, str]:
    return dict(_last_run.get(connector) or {})


def for_each_account(
    connector: str,
    items: Iterable[T],
    fn: Callable[[T], Iterable[dict]],
    *,
    account_id: Callable[[T], str],
    auth_errors: tuple[type[BaseException], ...] = (),
) -> list[dict]:
    """Run ``fn`` per account, isolating failures. ``auth_errors`` mark the
    account ``auth_required``; any other exception marks it ``error``.
    Returns the events from every account that succeeded."""
    _last_run[connector] = {}
    events: list[dict] = []
    for item in items:
        aid = account_id(item)
        try:
            got = list(fn(item))
        except auth_errors as e:
            log.warning("%s account %s needs re-auth: %s", connector, aid, e)
            record(connector, aid, STATUS_AUTH, str(e))
            continue
        except Exception as e:  # noqa: BLE001 — one account must never stop the rest
            log.warning("%s account %s failed: %s", connector, aid, e)
            record(connector, aid, STATUS_ERROR, str(e))
            continue
        record(connector, aid, STATUS_OK)
        events.extend(got)
    return events
```

- [ ] **Step 4: Integrate into `run_connector`**

In `ghostbrain/connectors/_runner.py`, add `from ghostbrain import accounts_health` to the imports. Replace the block from `queued = connector.run()` through its `return RunResult(... queued=int(queued),)` with:

```python
        accounts_health.clear_last_run(name)
        queued = connector.run()  # type: ignore[attr-defined]
        _audit("connector_run", name, events_queued=int(queued))
        summary = accounts_health.last_run_summary(name)
        details = {"accounts": summary} if summary else {}
        if summary and accounts_health.STATUS_OK not in summary.values():
            return RunResult(
                connector=name,
                ok=False,
                started_at=started,
                finished_at=time.time(),
                queued=int(queued),
                error="all accounts failed",
                error_type="AllAccountsFailed",
                details=details,
            )
        return RunResult(
            connector=name,
            ok=True,
            started_at=started,
            finished_at=time.time(),
            queued=int(queued),
            details=details,
        )
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_accounts_health.py tests/test_connector_base.py ghostbrain/api/tests/test_scheduler*.py tests/test_scheduler*.py -q -p no:cacheprovider`
Expected: PASS (ignore "file or directory not found" for a glob with no match — then drop that glob).

- [ ] **Step 6: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/accounts_health.py ghostbrain/connectors/_runner.py tests/test_accounts_health.py
git add ghostbrain/accounts_health.py ghostbrain/connectors/_runner.py tests/test_accounts_health.py
git commit -m "feat(accounts): per-account health + for_each_account; runner reports account breakdown

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Router account rule

**Files:**
- Modify: `ghostbrain/worker/router.py` (`_fast_route` and a new `_account_route`)
- Modify: `tests/test_slack_connector.py` (delete the three router tests at the end of the "router" section: `test_router_routes_by_workspace_slug`, `test_router_supports_legacy_string_value`, `test_router_falls_through_when_workspace_unknown`)
- Test: `tests/test_router_accounts.py`

**Interfaces:**
- Consumes: `accounts.account_connector_for_event(event)`, `accounts.context_for(connector, account_id)`.
- Produces: `_fast_route` returns `RoutingDecision(method="account", confidence=0.95)` when no specific rule matched and the event's `metadata.accountId` maps to an assigned context. The Slack workspace rule, the Jira site rule and the Google branch of the calendar rule are gone.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_router_accounts.py`:

```python
"""Account -> context routing sits after specific rules and before the LLM."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain.worker import router as router_mod


@pytest.fixture
def v(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    meta = root / "90-meta"
    meta.mkdir(parents=True)
    (meta / "routing.yaml").write_text(yaml.safe_dump({
        "contexts": ["personal", "agencyx", "agencyy"],
        "gmail": {"sender_domains": {"agencyx.com": "agencyx"}},
        "github": {"orgs": {"agencyy-org": "agencyy"}},
        "confluence": {"spaces": {"YDOCS": "agencyy"}},
        "calendar": {"macos": {"accounts": {"Work": "agencyx"}}},
    }), encoding="utf-8")
    (meta / "accounts.yaml").write_text(yaml.safe_dump({"version": 1, "accounts": [
        {"connector": "gmail", "id": "me@gmail.com", "context": "personal"},
        {"connector": "gmail", "id": "unassigned@gmail.com"},
        {"connector": "gmail", "id": "stale@gmail.com", "context": "gone"},
        {"connector": "slack", "id": "agencyx", "context": "agencyx"},
        {"connector": "calendar_google", "id": "me@agencyx.com", "context": "agencyx"},
        {"connector": "jira", "id": "agencyx.atlassian.net", "context": "agencyx"},
        {"connector": "confluence", "id": "agencyx.atlassian.net", "context": "agencyx"},
        {"connector": "github", "id": "nikrich", "context": "personal"},
        {"connector": "microsoft", "id": "me@agencyy.com", "context": "agencyy"},
    ]}), encoding="utf-8")
    return root


def _routing(root: Path) -> dict:
    return yaml.safe_load((root / "90-meta" / "routing.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("event,ctx", [
    ({"source": "gmail", "metadata": {"accountId": "me@gmail.com", "from_domain": "random.org"}}, "personal"),
    ({"source": "slack", "metadata": {"accountId": "agencyx", "workspace_slug": "agencyx"}}, "agencyx"),
    ({"source": "calendar", "metadata": {"provider": "google", "account": "me@agencyx.com",
                                         "accountId": "me@agencyx.com"}}, "agencyx"),
    ({"source": "jira", "metadata": {"accountId": "agencyx.atlassian.net", "site": "agencyx.atlassian.net"}}, "agencyx"),
    ({"source": "github", "metadata": {"accountId": "nikrich", "repo": "someone/else"}}, "personal"),
    ({"source": "teams_chat", "metadata": {"accountId": "ME@agencyy.com"}}, "agencyy"),
])
def test_account_rule_routes_each_connector(v, event, ctx):
    d = router_mod._fast_route({"id": "e1", **event}, _routing(v))
    assert d is not None
    assert (d.context, d.method, d.confidence) == (ctx, "account", 0.95)


def test_sender_domain_beats_account(v):
    ev = {"id": "e", "source": "gmail", "metadata": {"accountId": "me@gmail.com", "from_domain": "agencyx.com"}}
    d = router_mod._fast_route(ev, _routing(v))
    assert (d.context, d.method) == ("agencyx", "path")


def test_github_org_beats_account(v):
    ev = {"id": "e", "source": "github", "metadata": {"accountId": "nikrich", "org": "agencyy-org"}}
    d = router_mod._fast_route(ev, _routing(v))
    assert (d.context, d.method) == ("agencyy", "path")


def test_confluence_space_beats_account(v):
    ev = {"id": "e", "source": "confluence",
          "metadata": {"accountId": "agencyx.atlassian.net", "space": "YDOCS"}}
    d = router_mod._fast_route(ev, _routing(v))
    assert (d.context, d.method) == ("agencyy", "path")


def test_macos_calendar_rule_unaffected(v):
    ev = {"id": "e", "source": "calendar", "metadata": {"provider": "macos", "account": "Work", "accountId": "Work"}}
    d = router_mod._fast_route(ev, _routing(v))
    assert (d.context, d.method) == ("agencyx", "path")


@pytest.mark.parametrize("account_id", ["unassigned@gmail.com", "stale@gmail.com", "stranger@gmail.com", None])
def test_unassigned_or_stale_account_falls_through_to_llm(v, account_id):
    ev = {"id": "e", "source": "gmail", "metadata": {"accountId": account_id, "from_domain": "random.org"}}
    assert router_mod._fast_route(ev, _routing(v)) is None


def test_account_rule_skips_llm_in_route_event(v, monkeypatch):
    def no_llm(*a, **k):
        raise AssertionError("LLM must not be called")

    monkeypatch.setattr(router_mod, "_route_via_llm", no_llm)
    ev = {"id": "e", "source": "slack", "title": "hi", "body": "hello",
          "metadata": {"accountId": "agencyx", "workspace_slug": "agencyx"}}
    d = router_mod.route_event(ev, routing=_routing(v), config={})
    assert (d.context, d.method) == ("agencyx", "account")


def test_legacy_routing_blocks_no_longer_route(v):
    """The workspace/site/calendar-account rules moved into accounts.yaml."""
    routing = {**_routing(v),
               "slack": {"workspaces": {"legacy": {"context": "agencyx"}}},
               "jira": {"sites": {"legacy.atlassian.net": "agencyx"}},
               "calendar": {"google": {"accounts": {"legacy@x.com": "agencyx"}}}}
    for ev in (
        {"id": "e", "source": "slack", "metadata": {"workspace_slug": "legacy"}},
        {"id": "e", "source": "jira", "metadata": {"site": "legacy.atlassian.net"}},
        {"id": "e", "source": "calendar", "metadata": {"provider": "google", "account": "legacy@x.com"}},
    ):
        assert router_mod._fast_route(ev, routing) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_router_accounts.py -q -p no:cacheprovider`
Expected: FAIL — account-rule cases return `None`, legacy-block test returns decisions.

- [ ] **Step 3: Edit `ghostbrain/worker/router.py`**

1. Add `from ghostbrain import accounts` next to `from ghostbrain import routing_config`.
2. Delete the whole `if source == "jira":` block (site → context).
3. Delete the whole `if source == "slack":` block (workspace → context).
4. Replace the whole `if source == "calendar":` block with the macOS-only version:

```python
    if source == "calendar":
        provider = metadata.get("provider")
        account = metadata.get("account")
        if provider == "macos" and account:
            ctx = (
                ((routing.get("calendar") or {}).get("macos") or {})
                .get("accounts", {})
                .get(account)
            )
            if ctx:
                log.info("path-routed event=%s ctx=%s calendar=macos/%s",
                         event.get("id"), ctx, account)
                return RoutingDecision(
                    context=ctx,
                    confidence=1.0,
                    reasoning=f"matched calendar.macos.accounts rule for {account}",
                    method="path",
                )

    return _account_route(event)
```

   (That `return` replaces the old final `return None` of `_fast_route`.)
5. Add below `_fast_route`:

```python
def _account_route(event: dict) -> RoutingDecision | None:
    """Whole-account rule: every capture from an account assigned to a
    context lands there. Runs after every specific rule, before the LLM."""
    account_id = (event.get("metadata") or {}).get("accountId")
    ctx = accounts.context_for(accounts.account_connector_for_event(event), account_id)
    if not ctx:
        return None
    log.info("account-routed event=%s ctx=%s account=%s", event.get("id"), ctx, account_id)
    return RoutingDecision(
        context=ctx,
        confidence=0.95,
        reasoning=f"account {account_id} → {ctx}",
        method="account",
    )
```

6. In `RoutingDecision`, update the comment on `method` to `# "path" | "account" | "llm" | "fallback"`.
7. In `tests/test_slack_connector.py`, delete `test_router_routes_by_workspace_slug`, `test_router_supports_legacy_string_value` and `test_router_falls_through_when_workspace_unknown` (their behaviour is now covered by `test_router_accounts.py`).

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_router_accounts.py tests/test_router.py tests/test_router_contexts.py tests/test_router_projects.py tests/test_slack_connector.py tests/test_pipeline.py tests/test_note_generator.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/worker/router.py tests/test_router_accounts.py tests/test_slack_connector.py
git add ghostbrain/worker/router.py tests/test_router_accounts.py tests/test_slack_connector.py
git commit -m "feat(router): account -> context rule after specific rules; drop per-account routing.yaml rules

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Gmail on the registry

**Files:**
- Modify: `ghostbrain/connectors/gmail/connector.py` (`health_check`, `fetch`, `_normalize_thread`)
- Modify: `ghostbrain/connectors/gmail/runner.py`, `ghostbrain/connectors/gmail/__main__.py`, `ghostbrain/connectors/gmail/auth_cli.py`
- Test: `tests/test_multi_account_connectors.py` (new, shared by Tasks 4–8)

**Interfaces:**
- Consumes: `accounts.list_accounts("gmail")`, `accounts.ensure_account`, `accounts_health.for_each_account`.
- Produces: `gmail.runner._build(routing, queue_dir, state_dir) -> GmailConnector | None` built from the registry (reused by `__main__`); Gmail events carry `metadata.accountId`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_multi_account_connectors.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py -q -p no:cacheprovider`
Expected: FAIL — runner reads `routing.yaml`, no `accountId`, `health_check` all-or-nothing, CLI doesn't register.

- [ ] **Step 3: Connector changes (`ghostbrain/connectors/gmail/connector.py`)**

Add `from ghostbrain.accounts_health import for_each_account` to the imports. Replace `health_check` and the account loop at the top of `fetch`:

```python
    def health_check(self) -> bool:
        """True when at least one account has usable credentials — one
        lapsed token must not stop the others."""
        for acc in self.accounts:
            try:
                load_credentials(acc.email)
                return True
            except GmailAuthError:
                continue
        return False

    def fetch(self, since: datetime) -> list[dict]:
        if not self.accounts:
            log.info("no monitored gmail accounts configured; skipping")
            return []

        events = for_each_account(
            "gmail", self.accounts, self._fetch_account,
            account_id=lambda a: a.email, auth_errors=(GmailAuthError,),
        )

        raw_count = len(events)
        # ... (everything from `events = [e for e in events if not _is_denied(...)]` onward is unchanged)
```

In `_normalize_thread`'s `"metadata"` dict, add `"accountId": account,` right after `"account": account,`.

- [ ] **Step 4: Runner, CLI, auth CLI**

Replace `ghostbrain/connectors/gmail/runner.py` `_build` with:

```python
from ghostbrain import accounts


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> GmailConnector | None:
    accts = accounts.list_accounts("gmail")
    if not accts:
        return None
    gmail_cfg = routing.get("gmail") or {}
    return GmailConnector(
        config={
            "accounts": {a.id: dict(a.options) for a in accts},
            "denylist_domains": gmail_cfg.get("denylist_domains") or [],
            "relevance_gate": gmail_cfg.get("relevance_gate", True),
            "relevance_model": gmail_cfg.get("relevance_model"),
        },
        queue_dir=queue_dir,
        state_dir=state_dir,
    )
```

In `ghostbrain/connectors/gmail/__main__.py`: replace everything from `routing = _load_routing()` down to (and including) the `connector = GmailConnector(...)` call with:

```python
    routing = _load_routing()
    queue = queue_dir()
    state = state_dir()
    queue.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    from ghostbrain.connectors.gmail.runner import _build
    connector = _build(routing, queue, state)
    if connector is None:
        log.warning("No gmail accounts in 90-meta/accounts.yaml; nothing to fetch.")
        return
```

Remove the now-unused `GmailConnector` import there if ruff flags it, and update the module docstring's "Reads accounts from" line to `90-meta/accounts.yaml`.

In `ghostbrain/connectors/gmail/auth_cli.py`, after `path = run_oauth_flow(args.account)` succeeds (before the `print`), add:

```python
    from ghostbrain import accounts
    accounts.ensure_account("gmail", args.account)
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py tests/test_gmail_connector.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/connectors/gmail tests/test_multi_account_connectors.py
git add ghostbrain/connectors/gmail tests/test_multi_account_connectors.py
git commit -m "feat(gmail): accounts from registry, per-account isolation, accountId tagging

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Google Calendar on the registry (+ recorder meeting source)

**Files:**
- Modify: `ghostbrain/connectors/calendar/google/__init__.py` (`health_check`, `fetch`)
- Modify: `ghostbrain/connectors/calendar/_base.py` (`CalendarEvent.to_event` metadata)
- Modify: `ghostbrain/connectors/calendar/runner.py`, `ghostbrain/connectors/calendar/__main__.py`, `ghostbrain/connectors/calendar/auth_cli.py`
- Modify: `ghostbrain/recorder/sources/__init__.py` (`select_sources`), `tests/test_recorder_sources.py`
- Test: append to `tests/test_multi_account_connectors.py`

**Interfaces:**
- Consumes: `accounts.list_accounts("calendar_google")`, `for_each_account`.
- Produces: `calendar.runner.google_config() -> dict | None` — `{"accounts": {email: context_or_""}, "calendars_per_account": {email: [...]}}` or `None` when there are no Google accounts; `select_sources(routing, recorder_cfg, *, platform=None, google_accounts: dict[str, str] | None = None)`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_multi_account_connectors.py`)

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py -q -p no:cacheprovider -k "calendar or recorder"`
Expected: FAIL (`google_config` missing, no `accountId`, recorder reads routing).

- [ ] **Step 3: Implement**

`ghostbrain/connectors/calendar/_base.py` — in `to_event`'s `"metadata"`, add `"accountId": self.account,` after `"account": self.account,`.

`ghostbrain/connectors/calendar/google/__init__.py` — import `from ghostbrain.accounts_health import for_each_account`; replace `health_check` and the loop in `fetch`:

```python
    def health_check(self) -> bool:
        for email in self.account_contexts:
            try:
                load_credentials(email)
                return True
            except GoogleAuthError:
                continue
        return False

    def fetch(self, since: datetime) -> list[dict]:
        if not self.account_contexts:
            log.info("no google accounts configured; skipping")
            return []

        now = datetime.now(timezone.utc)
        time_min = (now - timedelta(hours=self.lookback_hours)).isoformat()
        time_max = (now + timedelta(hours=self.lookahead_hours)).isoformat()

        events = for_each_account(
            "calendar", list(self.account_contexts),
            lambda email: self._fetch_account(email, time_min, time_max),
            account_id=lambda email: email, auth_errors=(GoogleAuthError,),
        )
        log.info("google calendar fetch: %d event(s) across %d account(s)",
                 len(events), len(self.account_contexts))
        return events
```

`ghostbrain/connectors/calendar/runner.py` — add near the top:

```python
from ghostbrain import accounts


def google_config() -> dict | None:
    """GoogleCalendarConnector config from the registry, or None when no
    Google accounts are connected. Values are contexts ('' = unassigned);
    the connector only uses the keys, the recorder uses the values."""
    accts = accounts.list_accounts("calendar_google")
    if not accts:
        return None
    return {
        "accounts": {a.id: a.context or "" for a in accts},
        "calendars_per_account": {
            a.id: list(a.options["calendars"]) for a in accts if a.options.get("calendars")
        },
    }
```

and in `run()` replace the `google_cfg = ...` / `google_accounts = ...` / `if google_accounts:` block with:

```python
    google = google_config()
    if google:
        providers.append((
            "google",
            GoogleCalendarConnector(config=google, queue_dir=queue_dir, state_dir=state_dir),
        ))
```

Also add `from ghostbrain import accounts_health` and, in the final `RunResult`, set `details={"providers": per_provider, "accounts": accounts_health.last_run_summary("calendar")}`.

`ghostbrain/connectors/calendar/__main__.py` — replace the `google_cfg = ...` / `google_accounts = ...` / `if google_accounts and ...:` block with:

```python
    from ghostbrain.connectors.calendar.runner import google_config
    google = google_config()
    if google and (args.provider in (None, "google")):
        providers.append(("google", GoogleCalendarConnector(
            config=google, queue_dir=queue, state_dir=state,
        )))
```

`ghostbrain/connectors/calendar/auth_cli.py` — after `path = run_oauth_flow(args.account)` succeeds add:

```python
        from ghostbrain import accounts
        accounts.ensure_account("calendar_google", args.account)
```

`ghostbrain/recorder/sources/__init__.py` — change the signature to add `google_accounts: dict[str, str] | None = None` (keyword-only, after `platform`) and replace `google_accounts = (calendar.get("google") or {}).get("accounts") or {}` with:

```python
    if google_accounts is None:
        from ghostbrain import accounts
        google_accounts = {
            a.id: a.context for a in accounts.list_accounts("calendar_google") if a.context
        }
```

`tests/test_recorder_sources.py` — in `test_select_sources_from_configured_blocks` and `test_select_sources_override_pins_list`, delete the `"google": {"accounts": {...}}` entries from the routing dicts and pass `google_accounts={"a@x.com": "w"}` to each `select_sources(...)` call.

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py tests/test_recorder_sources.py tests/test_calendar.py tests/test_connector_probe_calendar.py -q -p no:cacheprovider`
Expected: PASS except the one pre-existing `test_calendar.py` failure.

- [ ] **Step 5: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/connectors/calendar ghostbrain/recorder/sources/__init__.py tests/test_multi_account_connectors.py tests/test_recorder_sources.py
git add ghostbrain/connectors/calendar ghostbrain/recorder/sources/__init__.py tests/test_multi_account_connectors.py tests/test_recorder_sources.py
git commit -m "feat(calendar): google accounts from registry; recorder source uses account contexts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Slack on the registry

**Files:**
- Modify: `ghostbrain/connectors/slack/connector.py` (`SlackWorkspaceConfig.context`, `_parse_workspaces`, `health_check`, `fetch`, `_normalize_message`, `_normalize_match`)
- Modify: `ghostbrain/connectors/slack/runner.py`, `ghostbrain/connectors/slack/__main__.py`, `ghostbrain/connectors/slack/token_cli.py`
- Modify: `tests/test_slack_connector.py` (`test_parse_workspaces_skips_entries_without_context`)
- Test: append to `tests/test_multi_account_connectors.py`

**Interfaces:**
- Produces: `slack.runner.workspaces_config() -> dict[str, dict]` (slug → options) from the registry; `SlackWorkspaceConfig.context: str | None = None`; Slack events carry `metadata.accountId = workspace_slug`.

- [ ] **Step 1: Write the failing tests** (append)

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py -q -p no:cacheprovider -k slack`
Expected: FAIL.

- [ ] **Step 3: Implement**

`connector.py`:
- `SlackWorkspaceConfig`: change `context: str` to `context: str | None = None  # informational; routing uses accounts.yaml` and move that field **below** `slug` only if Python complains about field order (it will not: `slug` is the only non-default field before it).
- `_parse_workspaces`: delete the `if not ctx: log.warning(...); continue` block and pass `context=str(ctx) if ctx else None`. Update the docstring example to drop `context:` as required.
- `health_check`:

```python
    def health_check(self) -> bool:
        for ws in self.workspaces:
            try:
                load_token(ws.slug)
                return True
            except SlackAuthError:
                continue
        return False
```

- `fetch`: import `from ghostbrain.accounts_health import for_each_account`; move the body of the current `for ws in self.workspaces: try: ...` (the `effective_mode` logic and the two `events.extend(...)` calls) into a new method, returning the list instead of extending:

```python
    def _fetch_one(self, ws: SlackWorkspaceConfig) -> list[dict]:
        effective_mode = ws.mode
        dm_only = ws.include_dms or ws.include_group_dms
        if effective_mode == "full" and not ws.allowed_channels and not dm_only:
            # (keep the existing explanatory comment block verbatim)
            log.warning(
                "slack %s: mode=full but no allowed_channels — "
                "falling back to mentions-mode for this run. "
                "Configure an allowlist to enable full-pull.",
                ws.slug,
            )
            effective_mode = "mentions"
        if effective_mode == "full":
            return list(self._fetch_workspace_full(ws))
        return list(self._fetch_workspace(ws))

    def fetch(self, since: datetime) -> list[dict]:
        if not self.workspaces:
            log.info("no slack workspaces configured; skipping")
            return []
        events = for_each_account(
            "slack", self.workspaces, self._fetch_one,
            account_id=lambda ws: ws.slug, auth_errors=(SlackAuthError,),
        )
        log.info("slack fetch: %d event(s) across %d workspace(s)",
                 len(events), len(self.workspaces))
        return events
```

- In both `_normalize_message` and `_normalize_match`, add `"accountId": workspace_slug,` next to `"workspace_slug": workspace_slug,` in the metadata dict.

`runner.py`:

```python
from ghostbrain import accounts


def workspaces_config() -> dict[str, dict]:
    return {a.id: dict(a.options) for a in accounts.list_accounts("slack")}


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> SlackConnector | None:
    workspaces = workspaces_config()
    if not workspaces:
        return None
    return SlackConnector(config={"workspaces": workspaces}, queue_dir=queue_dir, state_dir=state_dir)
```

`__main__.py`: replace `routing = _load_routing()` / `slack_cfg = ...` / `workspaces = slack_cfg.get("workspaces") or {}` with:

```python
    from ghostbrain.connectors.slack.runner import workspaces_config
    workspaces = workspaces_config()
```

and change the empty-case warning text to `"No slack accounts in 90-meta/accounts.yaml; nothing to fetch."`. Remove `_load_routing` if it becomes unused.

`token_cli.py`: after `path = save_token(args.workspace, args.token)` succeeds, add:

```python
    from ghostbrain import accounts
    accounts.ensure_account("slack", args.workspace)
```

and change the `workspace` argument help to `"Workspace slug (becomes the account id in 90-meta/accounts.yaml)."`.

`tests/test_slack_connector.py`: rename `test_parse_workspaces_skips_entries_without_context` to `test_parse_workspaces_keeps_entries_without_context` and change its assertions to:

```python
    slugs = [ws.slug for ws in out]
    assert slugs == ["acme", "broken"]
    assert [ws.context for ws in out] == ["work", None]
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py tests/test_slack_connector.py tests/test_slack_cursors.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/connectors/slack tests/test_multi_account_connectors.py tests/test_slack_connector.py
git add ghostbrain/connectors/slack tests/test_multi_account_connectors.py tests/test_slack_connector.py
git commit -m "feat(slack): workspaces from registry, context optional, per-workspace isolation

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Jira + Confluence on the registry (per-site identity)

**Files:**
- Modify: `ghostbrain/connectors/atlassian/_base.py` (`auth_for_site`, new `token_path`, `save_token`)
- Modify: `ghostbrain/connectors/jira/__init__.py`, `ghostbrain/connectors/jira/runner.py`, `ghostbrain/connectors/jira/__main__.py`
- Modify: `ghostbrain/connectors/confluence/__init__.py`, `ghostbrain/connectors/confluence/runner.py`, `ghostbrain/connectors/confluence/__main__.py`
- Modify: `ghostbrain/api/repo/import_atlassian.py` (`_confluence_config`, `_jira_sites`), `ghostbrain/api/repo/connector_probe.py` (`_atlassian_probe`), `tests/api/repo/test_connector_probe.py`
- Test: append to `tests/test_multi_account_connectors.py`

**Interfaces:**
- Produces:
  - `auth_for_site(host: str) -> tuple[str, str]` — email: registry (`jira` then `confluence` account `options.email`) → `ATLASSIAN_EMAIL`; token: `ATLASSIAN_TOKEN_<SLUG>` → `token_path(host)` file → `ATLASSIAN_TOKEN`.
  - `token_path(host: str) -> Path` = `state_dir()/f"atlassian.{slug_for_host(host).lower()}.token"`; `save_token(host: str, token: str) -> Path` (chmod 600).
  - `jira.runner.sites() -> list[str]`, `confluence.runner.sites() -> list[str]` (registry ids).
  - Jira/Confluence events carry `metadata.accountId = host`.

- [ ] **Step 1: Write the failing tests** (append)

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py -q -p no:cacheprovider -k "atlassian or jira or confluence"`
Expected: FAIL.

- [ ] **Step 3: Implement `_base.py` changes**

Update the module docstring's lookup list to the new order, then replace `auth_for_site` and add the helpers below it:

```python
def auth_for_site(host: str) -> tuple[str, str]:
    """Return ``(email, token)`` for the given Atlassian host.

    Email: the site's account in accounts.yaml (``options.email``, jira then
    confluence) → ``ATLASSIAN_EMAIL``. Token: ``ATLASSIAN_TOKEN_<SLUG>`` →
    ``state/atlassian.<slug>.token`` → ``ATLASSIAN_TOKEN``. The site-specific
    file wins over the global env token so an old single-agency token can't
    shadow another agency's site.

    Raises ``AtlassianAuthError`` when either is missing.
    """
    email = _registry_email(host) or os.environ.get("ATLASSIAN_EMAIL")
    if not email:
        raise AtlassianAuthError(
            f"No Atlassian email for {host}. Reconnect the site in the app, or set "
            "ATLASSIAN_EMAIL in .env."
        )

    slug = slug_for_host(host).upper().replace("-", "_")
    site_var = f"ATLASSIAN_TOKEN_{slug}"
    token = os.environ.get(site_var) or _read_token_file(host) or os.environ.get("ATLASSIAN_TOKEN")
    if not token:
        raise AtlassianAuthError(
            f"No API token for {host} ({site_var}, {token_path(host)}, or ATLASSIAN_TOKEN). "
            "Generate one at https://id.atlassian.com/manage-profile/security/api-tokens "
            "and reconnect the site in the app."
        )
    return (email, token)


def token_path(host: str) -> "Path":
    from ghostbrain.paths import state_dir

    return state_dir() / f"atlassian.{slug_for_host(host).lower()}.token"


def save_token(host: str, token: str) -> "Path":
    p = token_path(host)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token.strip(), encoding="utf-8")
    p.chmod(0o600)
    return p


def _read_token_file(host: str) -> str | None:
    try:
        return token_path(host).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _registry_email(host: str) -> str | None:
    from ghostbrain import accounts

    for connector in ("jira", "confluence"):
        acc = accounts.get_account(connector, host)
        if acc is not None and acc.options.get("email"):
            return str(acc.options["email"])
    return None
```

Add `from pathlib import Path` to the imports and drop the quotes on the `Path` annotations if you prefer.

- [ ] **Step 4: Jira + Confluence connectors, runners, CLIs**

In both `jira/__init__.py` and `confluence/__init__.py`: import `from ghostbrain.accounts_health import for_each_account`; replace `health_check` with the any-site version and the fetch loop with `for_each_account`:

```python
    # jira/__init__.py
    def health_check(self) -> bool:
        for host in self.sites:
            try:
                email, token = auth_for_site(host)
                AtlassianClient(host, email, token).get("/rest/api/3/myself")
                return True
            except Exception as e:  # noqa: BLE001
                log.warning("jira health check failed for %s: %s", host, e)
        return False
```

```python
        # inside fetch, replacing `events: list[dict] = []` + the `for host in self.sites:` loop
        events = for_each_account(
            "jira", self.sites, lambda host: list(self._fetch_site(host, since)),
            account_id=lambda host: host, auth_errors=(AtlassianAuthError,),
        )
```

Confluence is identical with `"confluence"`, `/wiki/rest/api/user/current`, and its log text. In each normalize function (`normalize_issue` in `jira/__init__.py`, the page normalizer in `confluence/__init__.py`), add `"accountId": host,` beside `"site": host,`.

`jira/runner.py`:

```python
from ghostbrain import accounts


def sites() -> list[str]:
    return [a.id for a in accounts.list_accounts("jira")]


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> JiraConnector | None:
    hosts = sites()
    if not hosts:
        return None
    return JiraConnector(config={"sites": hosts}, queue_dir=queue_dir, state_dir=state_dir)
```

`confluence/runner.py`:

```python
from ghostbrain import accounts


def sites() -> list[str]:
    return [a.id for a in accounts.list_accounts("confluence")]


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> ConfluenceConnector | None:
    spaces = dict((routing.get("confluence") or {}).get("spaces") or {})
    hosts = sites()
    if not hosts or not spaces:
        return None
    return ConfluenceConnector(
        config={"sites": hosts, "spaces": spaces}, queue_dir=queue_dir, state_dir=state_dir,
    )
```

`jira/__main__.py`: replace `sites = list((routing.get("jira") or {}).get("sites") or {})` with `from ghostbrain.connectors.jira.runner import sites as registry_sites` + `sites = registry_sites()`, warning text `"No jira accounts in 90-meta/accounts.yaml; nothing to fetch."`. `confluence/__main__.py`: replace the `sites = list(confluence_cfg.get("sites") or ...)` expression with `sites = registry_sites()` (imported from `confluence.runner`), warning text `"Connect a Confluence site and set confluence.spaces in routing.yaml; nothing to fetch."`.

- [ ] **Step 5: Import + probe**

`ghostbrain/api/repo/import_atlassian.py`:

```python
def _confluence_config(routing: dict) -> tuple[list[str], dict[str, str]]:
    from ghostbrain.connectors.confluence.runner import sites

    spaces = dict((routing.get("confluence") or {}).get("spaces") or {})
    hosts = sites()
    if not hosts or not spaces:
        raise ImportNotConfiguredError(CONFLUENCE_NOT_CONFIGURED)
    return hosts, spaces


def _jira_sites(routing: dict) -> list[str]:
    from ghostbrain.connectors.jira.runner import sites

    hosts = sites()
    if not hosts:
        raise ImportNotConfiguredError(JIRA_NOT_CONFIGURED)
    return hosts
```

`ghostbrain/api/repo/connector_probe.py` `_atlassian_probe`:

```python
def _atlassian_probe(connector_id: str) -> ProbeResult:
    from ghostbrain import accounts
    from ghostbrain.connectors.atlassian._base import AtlassianAuthError, auth_for_site

    accts = accounts.list_accounts(connector_id)
    if not accts:
        return ProbeResult("off")
    try:
        email, _ = auth_for_site(accts[0].id)
    except AtlassianAuthError as e:
        return ProbeResult("err", error=str(e))
    return ProbeResult("on", account=email)
```

`tests/api/repo/test_connector_probe.py`: in `test_jira_off_after_routing_sites_removed`, replace `remove_routing_path("jira.sites")` with `from ghostbrain import accounts; accounts.remove_account("jira", "acme.atlassian.net")` and rename the test to `test_jira_off_after_account_removed`. Any test there asserting an `err` state for "email xor token" keeps passing only if its setup yields an `AtlassianAuthError`; if one asserted the old `"Atlassian email or token missing"` string, change it to assert `r.state == "err"` only.

- [ ] **Step 6: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py tests/test_jira_connector.py tests/test_confluence_connector.py tests/test_atlassian_base.py tests/test_atlassian_import_refactor.py tests/api/repo/test_connector_probe.py ghostbrain/api/tests/test_import_items.py ghostbrain/api/tests/test_import_repo.py ghostbrain/api/tests/test_import_routes.py -q -p no:cacheprovider`
Expected: PASS. Import tests that seeded `jira.sites`/`confluence.sites` in `routing.yaml` still work because the registry seeds from those blocks on first read; if one writes `routing.yaml` *after* the registry was already read in the same test, write an `accounts.yaml` entry instead.

- [ ] **Step 7: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/connectors/atlassian ghostbrain/connectors/jira ghostbrain/connectors/confluence ghostbrain/api/repo/import_atlassian.py ghostbrain/api/repo/connector_probe.py tests/test_multi_account_connectors.py tests/api/repo/test_connector_probe.py
git add ghostbrain/connectors/atlassian ghostbrain/connectors/jira ghostbrain/connectors/confluence ghostbrain/api/repo/import_atlassian.py ghostbrain/api/repo/connector_probe.py tests/test_multi_account_connectors.py tests/api/repo/test_connector_probe.py
git commit -m "feat(atlassian): per-site accounts with their own email + token file; site isolation

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: GitHub — one account per gh login

**Files:**
- Modify: `ghostbrain/connectors/github/__init__.py`, `ghostbrain/connectors/github/runner.py`, `ghostbrain/connectors/github/__main__.py`
- Test: append to `tests/test_multi_account_connectors.py`

**Interfaces:**
- Produces: `GitHubConnector(config={"orgs": [...], "accounts": [login, ...]})`; `class GitHubAuthError(RuntimeError)`; `_token_for(login: str) -> str`; `_run_gh(args, *, timeout_s, env=None)`. With no accounts it behaves exactly as today (ambient `gh`, no `accountId`).

- [ ] **Step 1: Write the failing tests** (append)

```python
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


def test_github_runner_uses_registry_logins(v, tmp_path, monkeypatch):
    from ghostbrain.connectors.github import runner

    write_accounts(v, [{"connector": "github", "id": "nikrich"}])
    monkeypatch.setattr("shutil.which", lambda name: "/fake/gh")
    c = runner._build({"github": {"orgs": {"acme": "personal"}}}, tmp_path / "q", tmp_path / "s")
    assert c.accounts == ["nikrich"] and c.orgs == ["acme"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py -q -p no:cacheprovider -k github`
Expected: FAIL.

- [ ] **Step 3: Implement (`github/__init__.py`)**

1. Imports: add `import os` and `from ghostbrain.accounts_health import for_each_account`.
2. Add below the constants:

```python
class GitHubAuthError(RuntimeError):
    """`gh auth token --user <login>` failed — that login needs `gh auth login`."""
```

3. In `__init__`, after `self.orgs = ...` add `self.accounts: list[str] = [str(a) for a in (config.get("accounts") or [])]`.
4. Replace `health_check`:

```python
    def health_check(self) -> bool:
        if not self.accounts:
            try:
                proc = self._run_gh(["auth", "status"], timeout_s=15)
            except subprocess.SubprocessError:
                return False
            return proc.returncode == 0
        for login in self.accounts:
            try:
                self._token_for(login)
                return True
            except GitHubAuthError:
                continue
        return False

    def _token_for(self, login: str) -> str:
        try:
            proc = self._run_gh(
                ["auth", "token", "--hostname", "github.com", "--user", login], timeout_s=15,
            )
        except subprocess.SubprocessError as e:
            raise GitHubAuthError(f"gh auth token failed for {login}: {e}") from e
        token = (proc.stdout or "").strip()
        if proc.returncode != 0 or not token:
            raise GitHubAuthError(
                f"no gh token for {login}; run `gh auth login` as that account"
            )
        return token
```

5. Split `fetch`: keep the orgs guard, the `since` floor, `updated_qualifier` and `owner_csv` computation in `fetch`; move the three `events.extend(...)` searches into:

```python
    def _search_all(self, owner_csv: str, updated_qualifier: str, env: dict | None) -> list[dict]:
        events: list[dict] = []
        events.extend(self._search_prs(
            owner_csv, ["--author=@me", "--state=open", f"--updated={updated_qualifier}"],
            origin="authored", env=env,
        ))
        events.extend(self._search_prs(
            owner_csv, ["--review-requested=@me", "--state=open", f"--updated={updated_qualifier}"],
            origin="review-requested", env=env,
        ))
        events.extend(self._search_issues(
            owner_csv, ["--assignee=@me", "--state=open", f"--updated={updated_qualifier}"],
            origin="assigned", env=env,
        ))
        return events
```

and in `fetch`, replace the three searches with:

```python
        if not self.accounts:
            events = self._search_all(owner_csv, updated_qualifier, None)
        else:
            def one(login: str) -> list[dict]:
                env = {**os.environ, "GH_TOKEN": self._token_for(login)}
                found = self._search_all(owner_csv, updated_qualifier, env)
                for ev in found:
                    ev["metadata"]["accountId"] = login
                return found

            events = for_each_account(
                "github", self.accounts, one,
                account_id=lambda login: login, auth_errors=(GitHubAuthError,),
            )
```

   The existing de-dup by `(type, repo, number)` that follows stays unchanged — it now also de-duplicates across logins, first account wins.
6. Thread `env` through: `_search_prs(self, owner_csv, extra_args, *, origin, env=None)` and `_search_issues(..., env=None)` call `self._run_gh_json(cmd, env)`; `_run_gh_json(self, cmd, env=None)` calls `self._run_gh(cmd[1:], timeout_s=60, env=env)`; `_run_gh(self, args, *, timeout_s, env=None)` passes `env=env` to `subprocess.run`.

`github/runner.py`:

```python
from ghostbrain import accounts


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> GitHubConnector | None:
    orgs = list((routing.get("github") or {}).get("orgs") or {})
    if not orgs:
        return None
    return GitHubConnector(
        config={"orgs": orgs, "accounts": [a.id for a in accounts.list_accounts("github")]},
        queue_dir=queue_dir,
        state_dir=state_dir,
    )
```

`github/__main__.py`: replace the `connector = GitHubConnector(config={"orgs": orgs}, ...)` construction with `from ghostbrain.connectors.github.runner import _build` + `connector = _build(routing, queue, state)` (the `orgs` guard above it stays).

- [ ] **Step 4: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_multi_account_connectors.py tests/test_github_connector.py -q -p no:cacheprovider`
Expected: PASS (existing tests use the no-accounts path; their `_run_gh` patches accept the new `env` kwarg because `patch.object` mocks accept any args — if one uses a plain `side_effect` function with a fixed signature, add `env=None` to it).

- [ ] **Step 5: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/connectors/github tests/test_multi_account_connectors.py
git add ghostbrain/connectors/github tests/test_multi_account_connectors.py
git commit -m "feat(github): fetch per gh login via GH_TOKEN, never switching the active account

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Microsoft — several accounts in one MSAL cache

**Files:**
- Modify: `ghostbrain/connectors/microsoft/graph/auth.py`, `ghostbrain/connectors/microsoft/graph/auth_cli.py`
- Create: `ghostbrain/connectors/microsoft/graph/multi.py`
- Modify: `ghostbrain/connectors/microsoft/{outlook_mail,teams_chat,teams_meetings}/connector.py` and their `runner.py`
- Test: `tests/test_microsoft_multi_account.py`

**Interfaces:**
- Produces (auth.py):
  - `_build_app(config: dict, tenant_id: str | None = None)`
  - `get_token(config: dict, username: str | None = None, tenant_id: str | None = None) -> str`
  - `have_token(config: dict, username: str | None = None, tenant_id: str | None = None) -> bool`
  - `cached_usernames(config: dict) -> list[str]`
  - `remove_cached_account(config: dict, username: str) -> bool`
  - `username_from_result(result: dict, app) -> str` — `id_token_claims.preferred_username`, else the newest cached account's username, else `"your account"`.
  - `run_device_flow(config: dict, tenant_id: str | None = None) -> str`
- Produces (multi.py): `ms_accounts(config) -> list[dict]` (`[{"username", "tenant_id"}]`), `any_token(config) -> bool`, `fetch_per_account(connector: str, config: dict, fetch_with: Callable[[GraphClient], list[dict]]) -> list[dict]`.
- Runners pass `config["accounts"] = [{"username": a.id, "tenant_id": a.options.get("tenant_id")}]` from `list_accounts("microsoft")` and skip when empty.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_microsoft_multi_account.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from ghostbrain import accounts_health
from ghostbrain.connectors.microsoft.graph import auth, multi

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
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


def test_get_token_unknown_username_raises():
    app = MagicMock()
    app.get_accounts.return_value = []
    with patch.object(auth, "_build_app", return_value=app):
        with pytest.raises(auth.MicrosoftAuthError):
            auth.get_token(CFG, username="nobody@y.com")


def test_username_from_result_prefers_id_token_claims():
    app = MagicMock()
    app.get_accounts.return_value = [{"username": "first@x.com"}]
    assert auth.username_from_result({"id_token_claims": {"preferred_username": "new@y.com"}}, app) == "new@y.com"
    assert auth.username_from_result({}, app) == "first@x.com"


def test_remove_cached_account():
    app = MagicMock()
    app.get_accounts.return_value = [{"username": "a@x.com"}]
    with patch.object(auth, "_build_app", return_value=app):
        assert auth.remove_cached_account(CFG, "a@x.com") is True
    app.remove_account.assert_called_once_with({"username": "a@x.com"})


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


def test_runner_builds_accounts_from_registry(tmp_path: Path):
    from ghostbrain.connectors.microsoft.teams_chat import runner

    root = tmp_path / "vault"
    (root / "90-meta").mkdir(parents=True)
    (root / "90-meta" / "routing.yaml").write_text("contexts: [agencyy]\n", encoding="utf-8")
    (root / "90-meta" / "accounts.yaml").write_text(yaml.safe_dump({"version": 1, "accounts": [
        {"connector": "microsoft", "id": "me@agencyy.com", "options": {"tenant_id": "t-y"}},
    ]}), encoding="utf-8")
    routing = {"microsoft": {**CFG, "teams_chat": {}}}
    c = runner._build(routing, tmp_path / "q", tmp_path / "s")
    assert c.config["accounts"] == [{"username": "me@agencyy.com", "tenant_id": "t-y"}]
    (root / "90-meta" / "accounts.yaml").write_text("version: 1\naccounts: []\n", encoding="utf-8")
    assert runner._build(routing, tmp_path / "q", tmp_path / "s") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_microsoft_multi_account.py -q -p no:cacheprovider`
Expected: collection ERROR (`multi` missing).

- [ ] **Step 3: `auth.py`**

Replace `_build_app`, `get_token`, `have_token`, `run_device_flow` and add the helpers:

```python
def _build_app(config: dict, tenant_id: str | None = None):
    import msal

    client_id, default_tenant = resolve_app_config(config)
    authority = f"https://login.microsoftonline.com/{tenant_id or default_tenant}"
    return msal.PublicClientApplication(
        client_id, authority=authority, token_cache=_build_token_cache()
    )


def get_token(config: dict, username: str | None = None, tenant_id: str | None = None) -> str:
    """Access token for ``username`` (or the first cached account when None)
    from the shared cache. Raises MicrosoftAuthError when that account has no
    usable cached sign-in."""
    app = _build_app(config, tenant_id)
    accounts = app.get_accounts(username=username) if username else app.get_accounts()
    if not accounts:
        who = username or "any account"
        raise MicrosoftAuthError(
            f"No cached Microsoft sign-in for {who}. Reconnect it in the app "
            "or run: ghostbrain-microsoft-auth"
        )
    result = app.acquire_token_silent(resolve_scopes(config), account=accounts[0])
    if not result or "access_token" not in result:
        raise MicrosoftAuthError(
            f"Cached Microsoft sign-in for {accounts[0].get('username')} could not be "
            "refreshed. Reconnect it in the app or re-run: ghostbrain-microsoft-auth"
        )
    return result["access_token"]


def have_token(config: dict, username: str | None = None, tenant_id: str | None = None) -> bool:
    try:
        get_token(config, username, tenant_id)
        return True
    except MicrosoftAuthError:
        return False


def cached_usernames(config: dict) -> list[str]:
    app = _build_app(config)
    return [a["username"] for a in app.get_accounts() if a.get("username")]


def remove_cached_account(config: dict, username: str) -> bool:
    app = _build_app(config)
    found = app.get_accounts(username=username)
    for acc in found:
        app.remove_account(acc)
    return bool(found)


def username_from_result(result: dict, app) -> str:
    claims = result.get("id_token_claims") or {}
    if claims.get("preferred_username"):
        return str(claims["preferred_username"])
    accounts = app.get_accounts()
    return accounts[-1].get("username", "your account") if accounts else "your account"


def run_device_flow(config: dict, tenant_id: str | None = None) -> str:
    """Interactive device-code sign-in that ADDS an account to the shared
    cache (existing accounts stay). Returns the new account's username."""
    app = _build_app(config, tenant_id)
    flow = app.initiate_device_flow(scopes=resolve_scopes(config))
    if "user_code" not in flow:
        raise MicrosoftAuthError(f"Could not start device flow: {flow}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise MicrosoftAuthError(
            f"Auth failed: {result.get('error_description', result)}"
        )
    return username_from_result(result, app)
```

Update the module docstring: the cache can hold several accounts; scheduled fetches select one by username.

Note: `test_username_from_result_prefers_id_token_claims` expects `"first@x.com"` from a one-element list — `accounts[-1]` is that element.

`auth_cli.py`: add an optional `--tenant` argument (argparse), pass it to `run_device_flow(cfg, tenant_id=args.tenant)`, and after success:

```python
    from ghostbrain import accounts
    accounts.ensure_account("microsoft", username, options={"tenant_id": args.tenant} if args.tenant else None)
```

- [ ] **Step 4: `multi.py`**

```python
"""Per-account Graph fetch shared by the Outlook / Teams connectors."""
from __future__ import annotations

from typing import Callable

from ghostbrain.accounts_health import for_each_account
from ghostbrain.connectors.microsoft.graph.auth import MicrosoftAuthError, get_token, have_token
from ghostbrain.connectors.microsoft.graph.client import GraphClient


def ms_accounts(config: dict) -> list[dict]:
    return [a for a in (config.get("accounts") or []) if a.get("username")]


def any_token(config: dict) -> bool:
    return any(have_token(config, a["username"], a.get("tenant_id")) for a in ms_accounts(config))


def fetch_per_account(
    connector: str,
    config: dict,
    fetch_with: Callable[[GraphClient], list[dict]],
) -> list[dict]:
    """Run ``fetch_with(client)`` once per configured account with that
    account's token, tag events with ``metadata.accountId``, and isolate
    failures per account."""

    def one(acc: dict) -> list[dict]:
        client = GraphClient(get_token(config, acc["username"], acc.get("tenant_id")))
        events = fetch_with(client)
        for ev in events:
            ev.setdefault("metadata", {})["accountId"] = acc["username"]
        return events

    return for_each_account(
        connector, ms_accounts(config), one,
        account_id=lambda a: a["username"], auth_errors=(MicrosoftAuthError,),
    )
```

- [ ] **Step 5: Connectors and runners**

For each of the three connectors, the injected `client=` test seam keeps the old single-client behaviour; real runs go through `fetch_per_account`. Pattern (Outlook shown; apply the same shape to Teams Chat and Teams Meetings):

```python
    def health_check(self) -> bool:
        if self._client is not None:
            return True
        return any_token(self.config)

    def fetch(self, since: datetime) -> list[dict]:
        if self._client is not None:
            events = self._fetch_with(self._client, since)
        else:
            events = fetch_per_account("outlook_mail", self.config,
                                       lambda client: self._fetch_with(client, since))
        # ... denylist + relevance gate + log exactly as before, over `events`

    def _fetch_with(self, client, since: datetime) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        params = {...}  # unchanged
        msgs = client.get_all("/me/messages", params, max_items=self.max_per_run)
        return [_normalize_message(m, DEFAULT_BODY_CAP_CHARS) for m in msgs]
```

- Outlook: `_fetch_with` = the current `/me/messages` query + normalize; gate/denylist stay in `fetch`.
- Teams Chat: `_fetch_with(client, since)` = the current chats loop (with its per-chat `try/except` and `max_per_run` break) returning the collected events; the relevance gate stays in `fetch`.
- Teams Meetings: `_fetch_with(client, since)` = the current `refs = self._meeting_refs(client)` loop returning events; keep `except MicrosoftAuthError: raise` inside so an auth failure marks the account `auth_required`.
- Replace the imports of `get_token, have_token` in each connector with `from ghostbrain.connectors.microsoft.graph.multi import any_token, fetch_per_account`, and delete the now-unused `_graph()` methods (grep the tests first: if a test calls `_graph()`, keep it returning `self._client`).

Each runner's `_build` (shown for teams_chat; same for the other two with their block name):

```python
from ghostbrain import accounts


def _build(routing: dict, queue_dir: Path, state_dir: Path):
    ms = routing.get("microsoft") or {}
    cfg = ms.get("teams_chat")
    if cfg is None:
        return None
    accts = accounts.list_accounts("microsoft")
    if not accts:
        return None
    cfg = {
        **cfg,
        "client_id": ms.get("client_id"),
        "tenant_id": ms.get("tenant_id"),
        "scopes": ms.get("scopes"),
        "accounts": [{"username": a.id, "tenant_id": a.options.get("tenant_id")} for a in accts],
    }
    return TeamsChatConnector(config=cfg, queue_dir=queue_dir, state_dir=state_dir)
```

- [ ] **Step 6: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_microsoft_multi_account.py tests/test_microsoft_auth.py tests/test_microsoft_graph_client.py tests/test_outlook_mail_connector.py tests/test_teams_*.py tests/api/auth/providers/test_ms_device_code.py -q -p no:cacheprovider`
Expected: PASS. Existing connector tests inject `client=` and keep working; any that patched `get_token` in a connector module must now patch `multi.get_token`.

- [ ] **Step 7: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/connectors/microsoft tests/test_microsoft_multi_account.py
git add ghostbrain/connectors/microsoft tests/test_microsoft_multi_account.py
git commit -m "feat(microsoft): several accounts in one MSAL cache, per-tenant authority, per-account fetch

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: In-app connect flows and disconnect write the registry

**Files:**
- Modify: `ghostbrain/api/auth/providers/google_oauth.py`, `paste_token.py` (Slack only), `atlassian_api.py`, `ms_device_code.py`, `cli_login.py`
- Modify: `ghostbrain/api/auth/disconnect.py`
- Modify: `tests/api/auth/providers/test_atlassian_api.py` (`test_submit_writes_env_and_routing`), `tests/api/auth/test_disconnect.py` (`test_disconnect_jira_keeps_env_token`)
- Test: `tests/api/auth/test_providers_registry.py`

**Interfaces:**
- Consumes: `accounts.ensure_account`, `accounts.remove_account`, `atlassian._base.save_token/token_path`, `ms_auth.username_from_result`, `ms_auth.remove_cached_account`.
- Produces: every successful connect registers `(connector, id)` in `accounts.yaml` (unassigned unless it already existed); `DELETE /v1/connectors/{id}/credentials?account=X` also removes the account entry.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/auth/test_providers_registry.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/api/auth/test_providers_registry.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Providers**

`google_oauth.py` — in `poll`, after `m.run_oauth_flow(account)` succeeds and before setting `session.status = "success"`:

```python
        from ghostbrain import accounts
        accounts.ensure_account("gmail" if connector_id == "gmail" else "calendar_google", account)
```

`paste_token.py` (Slack `submit`) — replace the `merge_routing({"slack": ...})` call with:

```python
        from ghostbrain import accounts
        accounts.ensure_account("slack", slug)
```

(Keep `merge_routing` imported for Joplin.)

`atlassian_api.py` `submit` — replace `set_env(...)` and the first `merge_routing(...)` with:

```python
        from ghostbrain import accounts
        from ghostbrain.connectors.atlassian._base import save_token
        save_token(site, token)
        accounts.ensure_account(connector_id, site, options={"email": email})
```

Keep the Confluence `spaces` `merge_routing` block but merge them unassigned-free: change its values from `"needs_review"` to the site's context if the account has one, else omit the call — simplest correct form:

```python
        if connector_id == "confluence":
            spaces = [s.strip() for s in (data.get("spaces") or "").split(",") if s.strip()]
            if spaces:
                ctx = accounts.get_account("confluence", site).context or "needs_review"
                merge_routing({"confluence": {"spaces": {s: ctx for s in spaces}}})
```

Remove the `set_env` import. Change the success message to `"Connected. Connect the other Atlassian app separately if you use it."` (the old message claimed it connected both, which is no longer true since accounts are per app).

`ms_device_code.py` `poll` — replace the two lines that compute `session.account` from `app.get_accounts()` with:

```python
        from ghostbrain import accounts
        from ghostbrain.connectors.microsoft.graph.auth import username_from_result
        session.account = username_from_result(result, app)
        accounts.ensure_account("microsoft", session.account)
```

`cli_login.py` `poll` — after `session.account = login`, add:

```python
                if login:
                    from ghostbrain import accounts
                    accounts.ensure_account("github", login)
```

and do the same in `start` when `ok` is true (before returning the `done` action).

- [ ] **Step 4: `disconnect.py`**

At the end of `disconnect()` (after the per-connector branches), add registry removal, and change two branches:

```python
    # jira / confluence: replace the remove_routing_path branch with
    elif connector_id in ("jira", "confluence"):
        if account:
            from ghostbrain.connectors.atlassian._base import token_path
            other = "confluence" if connector_id == "jira" else "jira"
            from ghostbrain import accounts as _acc
            if _acc.get_account(other, account) is None:
                _rm(token_path(account))  # only when the other app doesn't use this site
    # microsoft: replace the whole-cache removal with
    elif connector_id in ("outlook_mail", "teams_chat", "teams_meetings"):
        from ghostbrain.connectors.microsoft.graph import auth as ms_auth
        if account:
            from ghostbrain.api.repo.routing import load_routing
            try:
                ms_auth.remove_cached_account(load_routing().get("microsoft") or {}, account)
            except Exception:  # noqa: BLE001 — best effort; the registry entry still goes
                pass
        else:
            _rm(ms_auth.cache_location())
```

and after the if/elif chain:

```python
    from ghostbrain import accounts
    acct_connector = accounts.SOURCE_TO_ACCOUNT_CONNECTOR.get(connector_id)
    if acct_connector and account:
        accounts.remove_account(acct_connector, account)
```

Order matters for jira/confluence: compute the "other app uses this site" check **before** `remove_account` runs (it does, since removal is after the chain).

- [ ] **Step 5: Update the two legacy-expectation tests**

`tests/api/auth/providers/test_atlassian_api.py::test_submit_writes_env_and_routing` → rename to `test_submit_registers_site_account` and assert: `accounts.get_account("jira", "acme.atlassian.net").options == {"email": "me@x.com"}` and `token_path("acme.atlassian.net").read_text() == "tok"` instead of the `.env` / `routing.yaml` assertions. Give its fixture a `90-meta/routing.yaml` with `contexts: [work]` if it lacks one.

`tests/api/auth/test_disconnect.py::test_disconnect_jira_keeps_env_token` → rename to `test_disconnect_jira_keeps_shared_site_token`: seed `accounts.upsert_account(Account("jira", "acme.atlassian.net"))`, the same for `confluence`, `save_token("acme.atlassian.net", "tok")`; call `disconnect("jira", account="acme.atlassian.net")`; assert the jira account is gone, the confluence account remains, and `token_path("acme.atlassian.net")` still exists (Confluence still uses it). Keep the `.env` preservation assertions if the test still seeds `.env` — `disconnect` never touches `.env`.

- [ ] **Step 6: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/api -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 7: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/api/auth tests/api/auth
git add ghostbrain/api/auth tests/api/auth
git commit -m "feat(auth): connect flows register accounts in accounts.yaml; disconnect removes one account

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Connectors API, doctor, desktop types

**Files:**
- Modify: `ghostbrain/api/models/connector.py`, `ghostbrain/api/repo/connectors.py` (`_connector_record`, `get_connector`)
- Modify: `ghostbrain/doctor/checks_connectors.py`, `tests/test_doctor_connector_checks.py`
- Modify: `desktop/src/shared/api-types.ts`
- Test: `ghostbrain/api/tests/test_connectors_accounts.py`

**Interfaces:**
- Produces:
  - pydantic `AccountHealth(status: str, checkedAt: str | None, lastSuccessAt: str | None, error: str | None)`, `ConnectorAccount(id: str, context: str | None, enabled: bool, health: AccountHealth | None)`; `ConnectorDetail.accounts: list[ConnectorAccount] = []`.
  - `Connector.account`: the id for one account, `"N accounts"` for several, else the probe's value.
  - `Connector.state == "err"` when the connector has enabled accounts and every one of them has health `auth_required`/`error`; `error` then reads `"all accounts need attention"`.
  - TS: `AccountHealth`, `ConnectorAccount`, `ConnectorDetail.accounts?: ConnectorAccount[]`.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_connectors_accounts.py`:

```python
from __future__ import annotations

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from ghostbrain import accounts_health


def _accounts(vault: Path, entries: list[dict]) -> None:
    (vault / "90-meta" / "accounts.yaml").write_text(
        yaml.safe_dump({"version": 1, "accounts": entries}), encoding="utf-8")


def test_detail_lists_accounts_with_health(client: TestClient, auth_headers, tmp_vault: Path):
    _accounts(tmp_vault, [
        {"connector": "gmail", "id": "a@x.com", "context": "work"},
        {"connector": "gmail", "id": "b@x.com"},
    ])
    accounts_health.record("gmail", "a@x.com", accounts_health.STATUS_OK)
    body = client.get("/v1/connectors/gmail", headers=auth_headers).json()
    assert body["account"] == "2 accounts"
    by_id = {a["id"]: a for a in body["accounts"]}
    assert by_id["a@x.com"]["context"] == "work"
    assert by_id["a@x.com"]["health"]["status"] == "ok"
    assert by_id["b@x.com"]["health"] is None


def test_single_account_summary_and_microsoft_shared(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "microsoft", "id": "me@agencyy.com"}])
    rows = {c["id"]: c for c in client.get("/v1/connectors", headers=auth_headers).json()}
    assert rows["teams_chat"]["account"] == "me@agencyy.com"
    assert rows["outlook_mail"]["account"] == "me@agencyy.com"


def test_state_err_when_every_account_failing(client, auth_headers, tmp_vault):
    _accounts(tmp_vault, [{"connector": "slack", "id": "a"}, {"connector": "slack", "id": "b"}])
    accounts_health.record("slack", "a", accounts_health.STATUS_AUTH, "revoked")
    accounts_health.record("slack", "b", accounts_health.STATUS_ERROR, "boom")
    row = next(c for c in client.get("/v1/connectors", headers=auth_headers).json() if c["id"] == "slack")
    assert row["state"] == "err" and row["error"] == "all accounts need attention"
    accounts_health.record("slack", "b", accounts_health.STATUS_OK)
    row = next(c for c in client.get("/v1/connectors", headers=auth_headers).json() if c["id"] == "slack")
    assert row["state"] != "err"
```

Update `tests/test_doctor_connector_checks.py`'s three connector tests to the registry seam (`_account_ids`):

```python
def test_connectors_flags_on_but_empty(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {"github": {"orgs": {}}})
    monkeypatch.setattr(cc, "_account_ids", lambda conn: ["acme"] if conn == "slack" else [])
    states = {"github": "on", "slack": "on", "gmail": "off"}
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult(states.get(cid, "off")))
    r = cc.check_connectors()
    assert r.status == "fail"
    assert r.data["on_but_empty"] == ["github"]
    assert r.data["configured"] == ["slack"]
    assert "github" in r.summary


def test_connectors_all_good(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {})
    monkeypatch.setattr(cc, "_account_ids", lambda conn: ["acme"] if conn == "slack" else [])
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult("on" if cid == "slack" else "off"))
    r = cc.check_connectors()
    assert r.status == "ok"
    assert r.data["configured"] == ["slack"]


def test_connectors_none_configured_is_warn(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {"github": {"orgs": {}}})
    monkeypatch.setattr(cc, "_account_ids", lambda conn: [])
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult("off"))
    assert cc.check_connectors().status == "warn"


def test_connectors_on_without_account_is_flagged(monkeypatch):
    monkeypatch.setattr(cc, "_routing", lambda: {})
    monkeypatch.setattr(cc, "_account_ids", lambda conn: [])
    monkeypatch.setattr(cc, "_probe", lambda cid: ProbeResult("on" if cid == "gmail" else "off"))
    r = cc.check_connectors()
    assert r.data["on_but_empty"] == ["gmail"]
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest ghostbrain/api/tests/test_connectors_accounts.py tests/test_doctor_connector_checks.py -q -p no:cacheprovider`
Expected: FAIL.

- [ ] **Step 3: Models**

In `ghostbrain/api/models/connector.py` add above `ConnectorDetail`:

```python
class AccountHealth(BaseModel):
    status: str
    checkedAt: str | None = None
    lastSuccessAt: str | None = None
    error: str | None = None


class ConnectorAccount(BaseModel):
    id: str
    context: str | None
    enabled: bool
    health: AccountHealth | None
```

and add `accounts: list[ConnectorAccount] = []` to `ConnectorDetail`.

- [ ] **Step 4: Repo**

In `ghostbrain/api/repo/connectors.py` add:

```python
def _accounts_for(connector_id: str) -> list[dict]:
    from ghostbrain import accounts, accounts_health

    acct_connector = accounts.SOURCE_TO_ACCOUNT_CONNECTOR.get(connector_id)
    if acct_connector is None:
        return []
    return [
        {
            "id": a.id,
            "context": a.context,
            "enabled": a.enabled,
            "health": accounts_health.health_for(connector_id, a.id),
        }
        for a in accounts.list_accounts(acct_connector, include_disabled=True)
    ]
```

In `_connector_record`, after computing `state` from the probe:

```python
    accts = _accounts_for(connector_id)
    account = p.account
    if len(accts) == 1:
        account = accts[0]["id"]
    elif len(accts) > 1:
        account = f"{len(accts)} accounts"
    error = p.error
    enabled = [a for a in accts if a["enabled"]]
    if enabled and all(
        (a["health"] or {}).get("status") in ("auth_required", "error") for a in enabled
    ):
        state = "err"
        error = "all accounts need attention"
```

and return `"account": account, "error": error` plus a private `"_accounts": accts` key. In `list_connectors`, strip it: `[{k: v for k, v in _connector_record(cid).items() if k != "_accounts"} for cid in ...]`. In `get_connector`, pop it into `"accounts"`:

```python
    base = _connector_record(connector_id)
    accts = base.pop("_accounts")
    ...
    return {**base, "accounts": accts, "scopes": ..., "pulls": ..., "vaultDestination": ...}
```

- [ ] **Step 5: Doctor**

Replace `_BLOCKS`, `_block_non_empty` and the loop in `check_connectors` in `ghostbrain/doctor/checks_connectors.py`:

```python
# Check order (also the order of `configured` in the result).
_ORDER = ("github", "gmail", "calendar", "slack", "jira", "confluence", "joplin", "claude_code")
# Connectors whose configuration is their accounts in 90-meta/accounts.yaml.
_ACCOUNT_BACKED = {"gmail": "gmail", "slack": "slack", "jira": "jira", "confluence": "confluence"}
# Connectors configured by a routing.yaml block: (top-level key, sub-key).
_BLOCKS: dict[str, tuple[str, str]] = {
    "github": ("github", "orgs"),
    "joplin": ("joplin", "token"),
    "claude_code": ("claude_code", "project_paths"),
}


def _account_ids(account_connector: str) -> list[str]:
    from ghostbrain import accounts

    return [a.id for a in accounts.list_accounts(account_connector)]


def _configured(cid: str, routing: dict) -> tuple[bool, bool]:
    """(has configuration, configuration is relevant for the on-but-empty check)."""
    if cid in _ACCOUNT_BACKED:
        return bool(_account_ids(_ACCOUNT_BACKED[cid])), True
    if cid == "calendar":
        macos = (((routing.get("calendar") or {}).get("macos") or {}).get("accounts")) or {}
        return bool(_account_ids("calendar_google") or macos), True
    key, sub = _BLOCKS[cid]
    return bool((routing.get(key) or {}).get(sub)), key in routing
```

and the loop:

```python
    for cid in _ORDER:
        has_config, relevant = _configured(cid, routing)
        state = _probe(cid).state
        if has_config:
            configured.append(cid)
        elif relevant and state == "on":
            on_but_empty.append(cid)
```

Change the fail `detail` text to: `"These show 'on' in the app because a credential exists, but no account (90-meta/accounts.yaml) or routing block (github orgs, joplin, claude_code) is configured, so every sync returns zero events. Reconnect through the app or add the account/org."`

- [ ] **Step 6: Desktop types**

In `desktop/src/shared/api-types.ts`, above `ConnectorDetail`:

```ts
export interface AccountHealth {
  status: 'ok' | 'auth_required' | 'error';
  checkedAt: string | null;
  lastSuccessAt: string | null;
  error: string | null;
}

export interface ConnectorAccount {
  id: string;
  context: string | null;
  enabled: boolean;
  health: AccountHealth | null;
}
```

and add `accounts?: ConnectorAccount[];` to `ConnectorDetail`.

- [ ] **Step 7: Run tests**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest ghostbrain/api/tests tests/test_doctor_connector_checks.py tests/api -q -p no:cacheprovider`
Then: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account/desktop && (test -d node_modules || npm ci) && npm run typecheck && npm test`
Expected: PASS (use `npm run typecheck`, not `tsc --noEmit`, which is a no-op in this repo).

- [ ] **Step 8: Ruff and commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/api/models/connector.py ghostbrain/api/repo/connectors.py ghostbrain/doctor/checks_connectors.py ghostbrain/api/tests/test_connectors_accounts.py tests/test_doctor_connector_checks.py
git add ghostbrain/api/models/connector.py ghostbrain/api/repo/connectors.py ghostbrain/doctor/checks_connectors.py ghostbrain/api/tests/test_connectors_accounts.py tests/test_doctor_connector_checks.py desktop/src/shared/api-types.ts
git commit -m "feat(api): connector detail lists accounts with health; doctor reads the registry

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Bootstrap template, docs, full verification

**Files:**
- Modify: `ghostbrain/bootstrap.py` (the `90-meta/routing.yaml` template comments)
- Modify: `docs/connectors.md`, `.claude/skills/onboarding-poltergeist/connectors.md`, `desktop/src/renderer/lib/setup-content.ts` (Gmail/Slack/Jira steps that tell users to edit per-account `routing.yaml` blocks)
- Test: `tests/test_bootstrap_contexts.py` and the full suite

- [ ] **Step 1: Bootstrap template**

In the `routing.yaml` template string in `ghostbrain/bootstrap.py`:
- Replace the Jira `sites:` block comment + `{}` and the Confluence `sites:` block with a single comment line in each section: `# Sites are accounts: connect them in the app (stored in 90-meta/accounts.yaml).` Keep `confluence.spaces`.
- Replace the whole `slack:` block with a comment: `# Slack workspaces are accounts: connect them in the app (90-meta/accounts.yaml).`
- In the `gmail:` block, replace `accounts:` + its example comments + `{}` with the comment `# Gmail accounts live in 90-meta/accounts.yaml (connect them in the app).` Keep `denylist_domains`, `relevance_gate`, `label_prefixes`, `sender_domains`.
- Add at the top, after the `contexts:` block:

```yaml
# Per-account settings (which Gmail / Slack / Atlassian / GitHub / Microsoft
# accounts are connected, and which context each routes to) live in
# 90-meta/accounts.yaml. Rules here that are more specific than an account
# (sender domains, labels, GitHub orgs, Confluence spaces) still win.
```

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest tests/test_bootstrap_contexts.py tests/test_bootstrap_routing_mode.py -q -p no:cacheprovider` — Expected: PASS (fix any assertion that pinned the removed example text by pointing it at the new comments).

- [ ] **Step 2: Docs**

- `docs/connectors.md`: add a section "Multiple accounts and contexts" explaining `90-meta/accounts.yaml` (format from spec §1), the routing order (specific rules → account → LLM), that connecting the same connector again adds another account, and that `needs re-auth` affects only that account. Update any per-connector step that says to add accounts/sites/workspaces to `routing.yaml`.
- `.claude/skills/onboarding-poltergeist/connectors.md`: same correction for the Gmail / Slack / Jira / Confluence steps (accounts come from the connect flow or `accounts.yaml`; `ghostbrain-*-auth` CLIs register the account automatically).
- `desktop/src/renderer/lib/setup-content.ts`: in the Gmail entry, replace the `routing.yaml` accounts snippet with `'# accounts.yaml is filled when you connect; set a context per account:\naccounts:\n  - connector: gmail\n    id: you@gmail.com\n    context: personal'` and the step text with `'Assign each account a context in 90-meta/accounts.yaml:'`. Do the same shape for any Slack/Jira snippet that shows per-account routing.yaml keys. Run `cd desktop && npm run typecheck && npm test` afterwards.

- [ ] **Step 3: Full verification**

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m pytest -q -p no:cacheprovider --ignore=tests/test_recorder_wasapi_io.py`
Expected: exactly the 22 baseline failures listed in Global Constraints, nothing else. If anything else fails, fix it before committing.

Run: `cd /Users/jannik/development/nikrich/ghost-brain-multi-account && .venv/bin/python -m ruff check ghostbrain/accounts.py ghostbrain/accounts_health.py ghostbrain/connectors ghostbrain/worker/router.py ghostbrain/api ghostbrain/doctor/checks_connectors.py ghostbrain/recorder/sources/__init__.py`
Expected: no findings in lines this branch added.

- [ ] **Step 4: Migration smoke test against a copy of a real-shaped vault**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && S=$(mktemp -d) && mkdir -p $S/vault/90-meta && cat > $S/vault/90-meta/routing.yaml <<'EOF'
contexts: [personal, agencyx]
gmail:
  accounts:
    me@gmail.com: {monitored_labels: [], unread_lookback_hours: 24}
  denylist_domains: ['*.uber.com']
slack:
  workspaces:
    agencyx: {context: agencyx, mode: mentions}
jira:
  sites:
    agencyx.atlassian.net: agencyx
EOF
VAULT_PATH=$S/vault GHOSTBRAIN_STATE_DIR=$S/state GHOSTBRAIN_ACCOUNTS_LIVE_SEED=0 .venv/bin/python -c "
from ghostbrain import accounts
from ghostbrain.worker.router import _fast_route
print(open('$S/vault/90-meta/accounts.yaml').read()) if accounts.list_accounts() else None
print(_fast_route({'id':'e','source':'slack','metadata':{'accountId':'agencyx'}}, {}))
"
```

Expected: an `accounts.yaml` listing the three accounts (gmail unassigned, slack + jira → agencyx), and a `RoutingDecision(context='agencyx', ..., method='account')`.

- [ ] **Step 5: Commit**

```bash
cd /Users/jannik/development/nikrich/ghost-brain-multi-account && git add ghostbrain/bootstrap.py docs/connectors.md .claude/skills/onboarding-poltergeist/connectors.md desktop/src/renderer/lib/setup-content.ts tests/
git commit -m "docs: accounts.yaml replaces per-account routing.yaml blocks

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## Self-review notes (plan author)

- Spec coverage: §1 file + seeding → Task 1; §2 registry/tagging/router/health/API → Tasks 1, 2, 3, 11 (tagging spread over 4–9); §3 per-connector → Tasks 4–9; §4 connect flows + other readers → Tasks 5 (recorder), 7 (import, probe), 10 (providers, disconnect), 11 (doctor); error-handling table → Task 1 (malformed, unknown, duplicates, stale context), Task 2 (all-failed, unreadable health), Tasks 4–9 (per-account isolation); testing section → each task's tests.
- Deliberate deviation from the spec text: no per-account Gmail `last_run` (spec amended — Gmail ignores `since`).
- Health keys use the fetching connector name (`outlook_mail`, not `microsoft`), so Outlook failing on a missing Mail.Read consent doesn't mark Teams as broken; the API looks health up by the same connector id.
