"""B4: semantic refresh writes related: through the vault write path.

No numpy here: these tests call the write helper directly, so they run in CI
(the [dev,api] install)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain.changes import log as changes
from ghostbrain.history import store

REL = "20-contexts/work/notes/plan.md"
V1 = (
    "---\nid: plan\n"
    'title: "Plan"   # pinned\n'
    "tags: [a, b]\nupdated: 2026-01-02\n---\n\n# Plan\n"
).encode()


def _refresh():
    from ghostbrain.semantic import refresh

    return refresh


@pytest.fixture
def note(vault: Path) -> Path:
    p = vault / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(V1)
    return p


def test_only_the_related_lines_change(note: Path) -> None:
    links = ["[[20-contexts/work/notes/other]]", "[[20-contexts/personal/x]]"]
    assert _refresh()._apply_related(REL, links) is True
    dump = yaml.safe_dump({"related": links}, default_flow_style=False, allow_unicode=True,
                          sort_keys=False)
    assert note.read_text() == V1.decode().replace("---\n\n#", dump + "---\n\n#", 1)


def test_unchanged_links_write_nothing(note: Path) -> None:
    r = _refresh()
    assert r._apply_related(REL, ["[[a]]"]) is True
    after = note.read_bytes()
    assert r._apply_related(REL, ["[[a]]"]) is False
    assert note.read_bytes() == after


def test_an_existing_related_block_is_replaced_in_place(vault: Path) -> None:
    p = vault / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nid: plan\nrelated:\n- '[[old]]'\nsource: manual\n---\n\nbody\n")
    assert _refresh()._apply_related(REL, ["[[new]]"]) is True
    assert p.read_text() == "---\nid: plan\nrelated:\n- '[[new]]'\nsource: manual\n---\n\nbody\n"


def test_unlisted_but_kept_in_page_history(note: Path) -> None:
    _refresh()._apply_related(REL, ["[[a]]"])
    assert changes.list_changes() == []
    [snap] = store.list_snapshots(REL)
    assert snap.actor == "worker:semantic-refresh" and store.get_blob(snap.blob) == V1


def test_a_failing_note_is_skipped_not_raised(note: Path, monkeypatch) -> None:
    from ghostbrain.vault_write import HistoryUnavailable, writer

    def boom(*_a, **_k):
        raise HistoryUnavailable("history unavailable: disk full")

    monkeypatch.setattr(writer, "_snapshot", boom)
    assert _refresh()._apply_related(REL, ["[[a]]"]) is False
    assert note.read_bytes() == V1


def test_missing_or_malformed_notes_are_skipped(vault: Path) -> None:
    r = _refresh()
    assert r._apply_related("20-contexts/work/gone.md", ["[[a]]"]) is False
    bad = vault / "20-contexts/work/bad.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\n- not: a mapping\n---\n\nbody\n")
    assert r._apply_related("20-contexts/work/bad.md", ["[[a]]"]) is False
    assert bad.read_text() == "---\n- not: a mapping\n---\n\nbody\n"
