"""B4: helpers for worker jobs that modify existing notes."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain import vault_write
from ghostbrain.changes import log as changes
from ghostbrain.history import store
from ghostbrain.vault_write import (
    UNLISTED_ACTORS,
    USER,
    WriteConflict,
    records_change,
    set_hold_policy,
    worker_actor,
    write,
)
from ghostbrain.vault_write import jobs

REL = "20-contexts/work/decisions/d1.md"
V1 = (
    b"---\nid: d1\n"
    b'title: "Use Postgres"   # chosen in review\n'
    b"tags: [db, infra]\nupdated: 2026-01-02\n---\n\n# Use Postgres\n"
)
JOB = worker_actor("reversal")


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"  # the root conftest points VAULT_PATH here
    (root / REL).parent.mkdir(parents=True)
    (root / REL).write_bytes(V1)
    return root


@pytest.fixture(autouse=True)
def _no_holds():
    """These tests are about the helpers; hold mechanics are B2/B3's."""
    set_hold_policy(lambda _p: [])
    yield
    set_hold_policy(None)


def test_update_fields_appends_only_the_new_key(vault):
    res = jobs.update_fields(REL, lambda meta: {"reversed_by": ["[[x]]"]}, actor=JOB, reason="linked")
    assert res is not None and res.status == "applied"
    assert (vault / REL).read_bytes() == V1.replace(b"---\n\n#", b"reversed_by:\n- '[[x]]'\n---\n\n#", 1)
    [row] = changes.list_changes()
    assert (row.actor, row.op, row.reason) == ("worker:reversal", "modify", "linked")


def test_bump_updated_is_opt_in(vault):
    jobs.update_fields(REL, lambda meta: {"related": ["[[y]]"]}, actor=JOB, reason="r",
                       bump_updated=True)
    assert b"updated: 2026-01-02" not in (vault / REL).read_bytes()


def test_nothing_to_change_writes_nothing(vault):
    assert jobs.update_fields(REL, lambda meta: {}, actor=JOB, reason="r") is None
    assert (vault / REL).read_bytes() == V1
    assert changes.list_changes() == []


def test_a_user_save_between_read_and_write_is_kept(vault):
    seen: list[dict] = []

    def compute(meta):
        seen.append(dict(meta))
        if len(seen) == 1:
            write(REL, fields={"reversed_by": ["[[mine]]"]}, actor=USER)  # the user, mid-job
        existing = list(meta.get("reversed_by") or [])
        return {"reversed_by": [*existing, "[[job]]"]}

    jobs.update_fields(REL, compute, actor=JOB, reason="linked")
    assert len(seen) == 2
    assert vault_write.read(REL).metadata()["reversed_by"] == ["[[mine]]", "[[job]]"]


def test_gives_up_after_three_attempts(vault):
    n = {"i": 0}

    def compute(_meta):
        n["i"] += 1
        (vault / REL).write_bytes(V1 + f"outside edit {n['i']}\n".encode())
        return {"x": n["i"]}

    with pytest.raises(WriteConflict):
        jobs.update_fields(REL, compute, actor=JOB, reason="r")
    assert n["i"] == jobs.MAX_ATTEMPTS


def test_a_held_job_write_leaves_the_note_alone(vault):
    set_hold_policy(lambda _p: ["held for test"])
    res = jobs.update_fields(REL, lambda meta: {"reversed_by": ["[[x]]"]}, actor=JOB, reason="r")
    assert res is not None and res.status == "pending"
    assert (vault / REL).read_bytes() == V1


def test_rewrite_text_is_verbatim_and_recorded(vault):
    rel = "80-profile/current-projects.md"
    (vault / rel).parent.mkdir(parents=True)
    (vault / rel).write_bytes(b"# Current projects\n\n## work\n")
    actor = worker_actor("profile-apply")
    res = jobs.rewrite_text(rel, lambda t: t + "- ship it", actor=actor, reason="added")
    assert (vault / rel).read_bytes() == b"# Current projects\n\n## work\n- ship it"
    row = changes.get(int(res.change_id))
    assert (row.actor, row.op) == ("worker:profile-apply", "modify")


def test_rewrite_text_creates_a_missing_file_without_a_row(vault):
    rel = "80-profile/_review.md"
    res = jobs.rewrite_text(rel, lambda t: "# Review\n" if t is None else t,
                            actor=worker_actor("profile-apply"), reason="r")
    assert res.status == "applied" and res.change_id is None  # a worker create is ingest
    assert (vault / rel).read_bytes() == b"# Review\n"


def test_rewrite_text_unchanged_writes_nothing(vault):
    assert jobs.rewrite_text(REL, lambda t: t, actor=JOB, reason="r") is None
    assert jobs.rewrite_text(REL, lambda t: None, actor=JOB, reason="r") is None
    assert (vault / REL).read_bytes() == V1


def test_semantic_refresh_is_unlisted():
    assert "worker:semantic-refresh" in UNLISTED_ACTORS
    assert records_change("worker:semantic-refresh", "modify") is False
    assert records_change("worker:reversal", "modify") is True


def test_an_unlisted_job_still_gets_page_history(vault):
    actor = worker_actor("semantic-refresh")
    res = jobs.update_fields(REL, lambda m: {"related": ["[[a]]"]}, actor=actor, reason="related")
    assert res.change_id is None and changes.list_changes() == []
    [snap] = store.list_snapshots(REL)
    assert snap.actor == "worker:semantic-refresh" and store.get_blob(snap.blob) == V1


def test_rewrite_text_retries_on_a_user_save_and_keeps_it(vault):
    rel = "80-profile/current-projects.md"
    (vault / rel).parent.mkdir(parents=True)
    (vault / rel).write_bytes(b"# Current projects\n")
    user_version = b"# Current projects\n\nmy own line\n"
    seen: list[str | None] = []

    def transform(text):
        seen.append(text)
        if len(seen) == 1:
            (vault / rel).write_bytes(user_version)  # the user saves mid-job
        return text + "- ship it\n"

    res = jobs.rewrite_text(rel, transform, actor=worker_actor("profile-apply"), reason="added")
    assert res is not None and res.status == "applied"
    assert seen == ["# Current projects\n", user_version.decode()]
    assert (vault / rel).read_bytes() == user_version + b"- ship it\n"


def test_rewrite_text_create_race_becomes_a_guarded_modify_of_the_users_file(vault):
    rel = "80-profile/_review.md"
    user_version = b"# Review\n\nwritten by me\n"
    seen: list[str | None] = []

    def transform(text):
        seen.append(text)
        if text is None:
            (vault / rel).parent.mkdir(parents=True, exist_ok=True)
            (vault / rel).write_bytes(user_version)  # the user creates it first
            return "# Review\n"
        return text + "- job line\n"

    res = jobs.rewrite_text(rel, transform, actor=worker_actor("profile-apply"), reason="r")
    assert seen == [None, user_version.decode()]
    assert (vault / rel).read_bytes() == user_version + b"- job line\n"
    assert res is not None and res.change_id is not None  # a worker modify is listed
    row = changes.get(int(res.change_id))
    assert (row.actor, row.op, row.rel_path) == ("worker:profile-apply", "modify", rel)


def test_rewrite_text_gives_up_when_the_file_keeps_changing(vault):
    n = {"i": 0}

    def transform(text):
        n["i"] += 1
        (vault / REL).write_bytes(V1 + f"outside edit {n['i']}\n".encode())
        return text + "job\n"

    with pytest.raises(WriteConflict):
        jobs.rewrite_text(REL, transform, actor=JOB, reason="r")
    assert n["i"] == jobs.MAX_ATTEMPTS
    assert (vault / REL).read_bytes() == V1 + f"outside edit {jobs.MAX_ATTEMPTS}\n".encode()
