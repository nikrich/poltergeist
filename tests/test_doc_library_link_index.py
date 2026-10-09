"""Library companion-note changes are reported to the A2 link index."""
from pathlib import Path

import pytest

from ghostbrain.api.repo.doc_library import folders, notes, ops
from tests.doc_library_helpers import lib_vault  # noqa: F401


@pytest.fixture(autouse=True)
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body")
    monkeypatch.setattr(ops, "_pdf_pages", lambda p: 3)
    monkeypatch.setattr(ops, "send2trash", lambda p: Path(p).unlink())


@pytest.fixture
def seen(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr("ghostbrain.vault_index.links.note_written", lambda rel, root=None: calls.append(rel))
    return calls


def test_upload_reports_note(lib_vault: Path, seen):
    s = ops.upload("work", "payments", "specs", "a.pdf", "", b"a")
    assert s["note_path"] in seen
    assert all(r.endswith(".md") for r in seen)


def test_rename_reports_note(lib_vault: Path, seen):
    s = ops.upload("work", None, "", "a.pdf", "", b"a")
    seen.clear()
    ops.rename(s["doc_id"], "Better")
    assert seen == [s["note_path"]]


def test_move_across_projects_reports_old_and_new(lib_vault: Path, seen):
    s = ops.upload("work", "payments", "", "a.pdf", "", b"a")
    seen.clear()
    m = ops.move(s["doc_id"], "work", "claims", "")
    assert m["note_path"] in seen and s["note_path"] in seen
    assert m["note_path"] != s["note_path"]


def test_delete_reports_note(lib_vault: Path, seen):
    s = ops.upload("work", None, "", "a.pdf", "", b"a")
    seen.clear()
    ops.delete(s["doc_id"])
    assert seen == [s["note_path"]]


def test_folder_move_reports_old_and_new(lib_vault: Path, seen):
    s = ops.upload("work", None, "a", "x.pdf", "", b"x")
    seen.clear()
    folders.move(("work", None, "a"), ("work", None, "b"))
    old = s["note_path"]
    new = old.replace("/docs/a/", "/docs/b/")
    assert old != new and old in seen and new in seen


def test_notify_skips_paths_outside_vault(lib_vault: Path, tmp_path: Path, seen):
    notes.notify_index(tmp_path / "elsewhere.md")
    assert seen == []
