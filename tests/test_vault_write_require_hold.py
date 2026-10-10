"""C4 Ruling B: ``require_hold`` fails closed. A write that asks to be held
is held, or refused before any byte, blob or change row is written."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.changes import log as changes
from ghostbrain.vault_write import (
    ASSISTANT,
    USER,
    NotHeldError,
    VaultWriteError,
    compute_etag,
    set_hold_policy,
    write,
)
from ghostbrain.vault_write import writer as vault_writer

TEMPLATE = "90-meta/templates/standup.md"
NOTE = "20-contexts/work/plan.md"
SOURCE = "---\ntemplate:\n  name: Standup\n---\n# Standup\n"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"  # the root conftest points VAULT_PATH here
    (root / NOTE).parent.mkdir(parents=True)
    (root / NOTE).write_bytes(V1)
    return root


@pytest.fixture(autouse=True)
def _default_policy():
    set_hold_policy(None)
    yield
    set_hold_policy(None)


@pytest.fixture
def blobs(monkeypatch) -> list[bytes]:
    stored: list[bytes] = []
    real = vault_writer._history_store.put_blob

    def spy(data: bytes) -> str:
        stored.append(data)
        return real(data)

    monkeypatch.setattr(vault_writer._history_store, "put_blob", spy)
    return stored


def test_not_held_error_is_a_vault_write_error():
    assert issubclass(NotHeldError, VaultWriteError)


def test_a_held_write_is_unchanged(vault, blobs):
    res = write(TEMPLATE, content=SOURCE, op="create", actor=ASSISTANT, reason="r",
                verbatim=True, require_hold=True)
    assert res.status == "pending" and res.change_id
    assert not (vault / TEMPLATE).exists()
    [row] = changes.list_changes(status="pending")
    assert (row.rel_path, row.actor, row.op) == (TEMPLATE, ASSISTANT, "create")
    assert blobs == [SOURCE.encode("utf-8")]


def test_a_policy_that_holds_nothing_writes_nothing(vault, blobs):
    set_hold_policy(lambda _proposal: [])
    with pytest.raises(NotHeldError):
        write(TEMPLATE, content=SOURCE, op="create", actor=ASSISTANT, reason="r",
              require_hold=True)
    assert not (vault / TEMPLATE).exists()
    assert not (vault / "90-meta").exists()
    assert changes.list_changes() == []
    assert blobs == []


def test_a_change_the_rules_do_not_hold_is_refused(vault, blobs):
    with pytest.raises(NotHeldError):
        write(NOTE, content="plain prose\n", actor=ASSISTANT, reason="r",
              base_etag=compute_etag(V1), require_hold=True)
    assert (vault / NOTE).read_bytes() == V1
    assert changes.list_changes() == []
    assert blobs == []


def test_a_user_write_is_never_held_so_it_is_refused(vault, blobs):
    with pytest.raises(NotHeldError):
        write(TEMPLATE, content=SOURCE, op="create", actor=USER, reason="r", require_hold=True)
    assert not (vault / TEMPLATE).exists()
    assert changes.list_changes() == []
    assert blobs == []


def test_an_approved_write_is_refused(vault):
    held = write(TEMPLATE, content=SOURCE, op="create", actor=ASSISTANT, reason="r")
    assert held.status == "pending"
    with pytest.raises(NotHeldError):
        write(TEMPLATE, content=SOURCE, op="create", actor=ASSISTANT, reason="r",
              approved_change=int(held.change_id), require_hold=True)
    assert not (vault / TEMPLATE).exists()
    [row] = changes.list_changes()
    assert row.status == "pending"


def test_a_modify_that_changes_nothing_is_refused(vault):
    set_hold_policy(lambda _proposal: ["always"])
    with pytest.raises(NotHeldError):
        write(NOTE, content=V1.decode("utf-8"), actor=ASSISTANT, reason="r",
              base_etag=compute_etag(V1), require_hold=True)
    assert changes.list_changes() == []


def test_without_require_hold_an_unheld_write_still_applies(vault):
    set_hold_policy(lambda _proposal: [])
    res = write(TEMPLATE, content=SOURCE, op="create", actor=ASSISTANT, reason="r")
    assert res.status == "applied"
    assert (vault / TEMPLATE).read_text(encoding="utf-8") == SOURCE
