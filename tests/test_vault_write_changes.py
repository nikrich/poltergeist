"""B2: the vault write path records non-user changes in the change log."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import (
    ASSISTANT,
    MCP,
    RESTORE,
    USER,
    EtagRequired,
    HistoryUnavailable,
    ProposedChange,
    compute_etag,
    plugin_actor,
    set_hold_policy,
    worker_actor,
    write,
    write_new,
)

REL = "20-contexts/work/plan.md"
V1 = b"---\ntitle: Plan\n---\n\nfirst draft\n"
FAMILIAR = plugin_actor("familiar")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"  # the root conftest points VAULT_PATH here
    note = root / REL
    note.parent.mkdir(parents=True)
    note.write_bytes(V1)
    return root


@pytest.fixture(autouse=True)
def _default_policy():
    yield
    set_hold_policy(None)


def _row(res) -> changes.Change:
    assert res.change_id is not None
    row = changes.get(int(res.change_id))
    assert row is not None
    return row


def test_assistant_edit_records_before_and_after(vault):
    res = write(REL, body="polished draft", actor=ASSISTANT, base_etag=compute_etag(V1),
                reason="polished intro")
    row = _row(res)
    on_disk = (vault / REL).read_bytes()
    assert (row.actor, row.op, row.rel_path, row.dest_path, row.status) == (
        "assistant", "modify", REL, None, "applied")
    assert row.reason == "polished intro"
    assert store.get_blob(row.before_blob) == V1
    assert store.get_blob(row.after_blob) == on_disk
    assert res.etag == compute_etag(on_disk)


def test_user_and_restore_writes_get_no_row(vault):
    assert write(REL, body="mine", actor=USER).change_id is None
    assert write(REL, content=V1.decode(), actor=RESTORE).change_id is None
    assert changes.list_changes() == []


def test_assistant_created_note_is_applied_now_and_recorded(vault):
    res = write_new("20-contexts/work/new.md", "# New\n", actor=ASSISTANT, reason="drafted")
    assert res.status == "applied"
    assert (vault / "20-contexts/work/new.md").read_bytes() == b"# New\n"
    row = _row(res)
    assert (row.op, row.before_blob) == ("create", None)
    assert store.get_blob(row.after_blob) == b"# New\n"


def test_worker_creation_is_ingest_but_worker_edits_are_recorded(vault):
    ingest = write("20-contexts/work/gmail/t.md", content="mail\n", op="create",
                   actor=worker_actor("gmail"))
    assert ingest.change_id is None
    edit = write(REL, fields={"routingStatus": "routed"}, actor=worker_actor("jot-router"))
    assert _row(edit).actor == "worker:jot-router"


def test_move_and_delete_rows(vault):
    dest = "20-contexts/work/projects/plan.md"
    moved = write(REL, op="move", dest=dest, fields={"context": "work"}, actor=FAMILIAR,
                  base_etag=compute_etag(V1))
    row = _row(moved)
    assert (row.op, row.rel_path, row.dest_path) == ("move", REL, dest)
    assert store.get_blob(row.before_blob) == V1
    assert store.get_blob(row.after_blob) == (vault / dest).read_bytes()
    gone = write(dest, op="delete", actor=ASSISTANT, base_etag=vault_write.current_etag(dest))
    drow = _row(gone)
    assert (drow.op, drow.after_blob) == ("delete", None)
    assert store.get_blob(drow.before_blob) == store.get_blob(row.after_blob)


def test_identical_write_records_nothing(vault):
    res = write(REL, content=V1.decode(), actor=ASSISTANT, base_etag=compute_etag(V1))
    assert res.change_id is None
    assert changes.list_changes() == []


def test_non_user_edit_without_an_etag_is_refused(vault):
    with pytest.raises(EtagRequired) as exc:
        write(REL, content="plugin text\n", actor=FAMILIAR)
    assert exc.value.current_etag == compute_etag(V1)
    assert (vault / REL).read_bytes() == V1


def test_a_plugin_may_rewrite_its_own_untouched_note_without_an_etag(vault):
    rel = "Familiar/memory.md"
    write(rel, content="v1\n", op="create", actor=FAMILIAR)
    write(rel, content="v2\n", actor=FAMILIAR)  # implicit base: its own last write
    assert (vault / rel).read_bytes() == b"v2\n"
    (vault / rel).write_bytes(b"user edit\n")
    with pytest.raises(EtagRequired):
        write(rel, content="v3\n", actor=FAMILIAR)
    assert (vault / rel).read_bytes() == b"user edit\n"


def test_another_actors_last_write_is_not_an_implicit_base(vault):
    rel = "Familiar/memory.md"
    write(rel, content="v1\n", op="create", actor=FAMILIAR)
    with pytest.raises(EtagRequired):
        write(rel, content="hijack\n", actor=plugin_actor("other"))


def test_a_broken_change_log_fails_closed_for_implicit_bases(vault, monkeypatch):
    rel = "Familiar/memory.md"
    write(rel, content="v1\n", op="create", actor=FAMILIAR)

    def boom(*_a, **_k):
        raise changes.ChangeLogError("database is locked")

    monkeypatch.setattr(changes, "last_after_blob", boom)
    with pytest.raises(EtagRequired):
        write(rel, content="v2\n", actor=FAMILIAR)


def test_change_log_failure_after_the_write_keeps_the_write(vault, monkeypatch):
    def boom(**_k):
        raise changes.ChangeLogError("disk full")

    monkeypatch.setattr(changes, "record", boom)
    res = write(REL, body="ai edit", actor=ASSISTANT, base_etag=compute_etag(V1))
    assert res.status == "applied" and res.change_id is None
    assert b"ai edit" in (vault / REL).read_bytes()
    assert changes.degraded() is not None


def test_blob_store_failure_refuses_a_non_user_create(vault, monkeypatch):
    def boom(_data):
        raise OSError("disk full")

    monkeypatch.setattr(store, "put_blob", boom)
    with pytest.raises(HistoryUnavailable):
        write("20-contexts/work/new.md", content="x\n", op="create", actor=MCP)
    assert not (vault / "20-contexts/work/new.md").exists()


def test_hold_policy_hook_records_pending_and_writes_nothing(vault):
    seen: list[ProposedChange] = []

    def hold(p: ProposedChange) -> list[str]:
        seen.append(p)
        return ["touches config"]

    set_hold_policy(hold)
    res = write(REL, body="risky", actor=ASSISTANT, base_etag=compute_etag(V1), reason="r")
    assert res.status == "pending" and res.etag == compute_etag(V1)
    assert (vault / REL).read_bytes() == V1
    row = _row(res)
    assert (row.status, row.risk_reasons, row.after_blob) == ("pending", ("touches config",), None)
    assert store.get_blob(row.before_blob) == V1
    assert b"risky" in store.get_blob(row.pending_bytes_blob)
    [p] = seen
    assert (p.actor, p.op, p.rel_path, p.dest_path, p.before) == (
        "assistant", "modify", REL, None, V1)
    assert store.list_snapshots(REL) == []


def test_user_writes_never_reach_the_hold_policy(vault):
    set_hold_policy(lambda _p: ["always"])
    assert write(REL, body="mine", actor=USER).status == "applied"


def test_a_failing_hold_policy_holds_the_change(vault):
    def broken(_p):
        raise RuntimeError("bug in a rule")

    set_hold_policy(broken)
    res = write(REL, body="x", actor=ASSISTANT, base_etag=compute_etag(V1))
    assert res.status == "pending"
    assert _row(res).risk_reasons == ("risk check failed",)


def test_verbatim_content_keeps_the_bytes_exact(vault):
    write(REL, content="no trailing newline", actor=USER, verbatim=True)
    assert (vault / REL).read_bytes() == b"no trailing newline"


def test_move_can_carry_replacement_content(vault):
    dest = "20-contexts/work/archive/plan.md"
    res = write(REL, op="move", dest=dest, content="replaced\n", actor=USER)
    assert res.path == dest
    assert not (vault / REL).exists()
    assert (vault / dest).read_bytes() == b"replaced\n"


def test_package_exports_the_b2_surface():
    for name in ("EtagRequired", "ProposedChange", "HoldPolicy", "set_hold_policy",
                 "records_change", "needs_base_etag"):
        assert hasattr(vault_write, name)
    assert vault_write.records_change("assistant", "modify") is True
    assert vault_write.records_change("restore", "modify") is False
    assert vault_write.records_change("user", "create") is False
    assert vault_write.records_change("worker:gmail", "create") is False
    assert vault_write.records_change("worker:jot-router", "move") is True
    assert vault_write.needs_base_etag("plugin:x") is True
    assert vault_write.needs_base_etag("worker:x") is False
    assert vault_write.needs_base_etag("user") is False
