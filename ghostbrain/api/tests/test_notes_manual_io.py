"""Filesystem ops on the manual jot vault location."""
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import pytest

from ghostbrain.api.repo.notes_manual import (
    JotIdConflict,
    JotNotFound,
    delete_jot,
    list_jots,
    mark_manual_review,
    move_jot,
    read_jot,
    update_jot_body,
    write_inbox_jot,
)


@pytest.fixture
def vault(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "00-inbox" / "raw" / "manual").mkdir(parents=True)
    (tmp_path / "20-contexts" / "sanlam" / "notes").mkdir(parents=True)
    return tmp_path


def test_write_inbox_jot_creates_file_with_frontmatter(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    record = write_inbox_jot("ghostbrain idea\n\nbody #ui", captured_at=when)
    assert record["id"] == "manual-20260514T093015-ghostbrain-idea"
    p = vault / record["path"]
    assert p.exists()
    fm = frontmatter.load(p)
    assert fm["source"] == "manual"
    assert fm["routingStatus"] == "pending"
    assert fm["tags"] == ["ui"]
    assert "body #ui" in fm.content


def test_write_inbox_jot_id_collision_appends_suffix(vault, monkeypatch):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual._random_suffix",
        lambda: "abcd",
    )
    a = write_inbox_jot("same first line", captured_at=when)
    b = write_inbox_jot("same first line", captured_at=when)
    assert a["id"] != b["id"]
    assert b["id"].endswith("-abcd")


def test_list_jots_walks_inbox_and_routed_locations(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    inbox = write_inbox_jot("first jot", captured_at=when)
    later = datetime(2026, 5, 14, 10, 0, 0, tzinfo=timezone.utc)
    routed = write_inbox_jot("second jot routed", captured_at=later)
    move_jot(routed["id"], to_context="sanlam", confidence=0.82, method="llm",
             reasoning="test")
    page = list_jots()
    assert page["total"] == 2
    ids = [item["id"] for item in page["items"]]
    assert ids[0] == routed["id"]  # newer first
    assert ids[1] == inbox["id"]


def test_list_jots_respects_context_filter(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    a = write_inbox_jot("a", captured_at=when)
    b = write_inbox_jot("b", captured_at=when.replace(second=20))
    move_jot(b["id"], to_context="sanlam", confidence=1.0, method="user",
             reasoning="manual")
    page = list_jots(context="sanlam")
    assert [item["id"] for item in page["items"]] == [b["id"]]
    _ = a  # silence linter


def test_list_jots_substring_q_matches_title_and_body(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    write_inbox_jot("ghostbrain idea about ascp", captured_at=when)
    write_inbox_jot("unrelated thought", captured_at=when.replace(second=20))
    page = list_jots(q="ascp")
    assert page["total"] == 1
    assert "ascp" in page["items"][0]["title"]


def test_list_jots_tag_filter(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    write_inbox_jot("a #ui", captured_at=when)
    write_inbox_jot("b", captured_at=when.replace(second=20))
    page = list_jots(tag="ui")
    assert page["total"] == 1


def test_read_jot_returns_frontmatter_and_body(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("my jot", captured_at=when)
    note = read_jot(rec["id"])
    assert note["body"].startswith("my jot")
    assert note["frontmatter"]["id"] == rec["id"]


def test_read_jot_unknown_raises(vault):
    with pytest.raises(JotNotFound):
        read_jot("manual-20990101T000000-nope")


def test_update_jot_body_rewrites_file_and_bumps_updated(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("original", captured_at=when)
    original_updated = read_jot(rec["id"])["frontmatter"]["updated"]
    # `updated` is stamped from the wall clock on rewrite; the original value
    # equals captured_at (2026-05-14), so the two always differ.
    update_jot_body(rec["id"], "rewritten body #new")
    after = read_jot(rec["id"])
    assert after["body"].strip() == "rewritten body #new"
    assert after["frontmatter"]["tags"] == ["new"]
    assert after["frontmatter"]["updated"] != original_updated


def test_move_jot_moves_file_and_updates_frontmatter(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("routing me", captured_at=when)
    move_jot(rec["id"], to_context="sanlam", confidence=0.7, method="llm",
             reasoning="content matches sanlam terminology")
    note = read_jot(rec["id"])
    assert note["path"].startswith("20-contexts/sanlam/notes/")
    assert note["frontmatter"]["context"] == "sanlam"
    assert note["frontmatter"]["routingStatus"] == "routed"
    assert note["frontmatter"]["routingConfidence"] == 0.7


def test_delete_jot_removes_file(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("ephemeral", captured_at=when)
    delete_jot(rec["id"])
    with pytest.raises(JotNotFound):
        read_jot(rec["id"])


def test_mark_manual_review_flips_status_in_place(vault):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("ambiguous thought", captured_at=when)
    result = mark_manual_review(rec["id"], reasoning="no classifiable content")
    assert result["routingStatus"] == "manual_review"
    note = read_jot(rec["id"])
    assert note["path"].startswith("00-inbox/raw/manual/")  # file did not move
    assert note["frontmatter"]["routingStatus"] == "manual_review"
    assert note["frontmatter"]["routingReasoning"] == "no classifiable content"


def test_write_inbox_jot_double_collision_raises(vault, monkeypatch):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "ghostbrain.api.repo.notes_manual._random_suffix",
        lambda: "abcd",
    )
    inbox = vault / "00-inbox" / "raw" / "manual"
    base = "manual-20260514T093015-same-first-line"
    (inbox / f"{base}.md").touch()
    (inbox / f"{base}-abcd.md").touch()
    with pytest.raises(JotIdConflict):
        write_inbox_jot("same first line", captured_at=when)


def test_read_jot_rejects_path_traversal(vault):
    with pytest.raises(JotNotFound):
        read_jot("../../etc/passwd")


def test_move_jot_rejects_path_traversal_context(vault, tmp_path):
    when = datetime(2026, 5, 14, 9, 30, 15, tzinfo=timezone.utc)
    rec = write_inbox_jot("stay put", captured_at=when)
    with pytest.raises(ValueError):
        move_jot(rec["id"], to_context="../../outside", confidence=1.0,
                 method="user", reasoning="evil")
    assert not (tmp_path.parent / "outside").exists()
    # file untouched in the inbox
    assert read_jot(rec["id"])["path"].startswith("00-inbox/raw/manual/")
