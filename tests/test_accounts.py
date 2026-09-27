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


def test_ensure_account_merges_options_when_stored_context_was_removed(v):
    _write_accounts(v, [{"connector": "jira", "id": "gone.atlassian.net", "context": "retired",
                         "options": {"email": "old@x.com"}}])
    acc = accounts.ensure_account("jira", "gone.atlassian.net", options={"email": "new@x.com"})
    assert acc.context == "retired"
    assert acc.options == {"email": "new@x.com"}
    stored = accounts.get_account("jira", "gone.atlassian.net")
    assert stored.context == "retired" and stored.options == {"email": "new@x.com"}


def test_cross_process_lock_lives_in_state_dir_not_vault(v, tmp_path):
    _write_accounts(v, [])
    accounts.upsert_account(accounts.Account("gmail", "a@x.com"))
    assert not (v / "90-meta" / ".accounts.lock").exists()
    if accounts.fcntl is not None:
        assert (tmp_path / "state" / "accounts.lock").exists()
