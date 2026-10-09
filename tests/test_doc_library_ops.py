"""Move / rename / delete / reindex (spec §2, §7)."""
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import index, notes, ops
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidRequest
from tests.doc_library_helpers import lib_vault  # noqa: F401


@pytest.fixture(autouse=True)
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda n, m, s: "body")
    monkeypatch.setattr(ops, "_pdf_pages", lambda p: 3)


def test_move_across_projects_keeps_note_basename(lib_vault: Path):
    s = ops.upload("work", "payments", "specs", "a.pdf", "", b"a")
    note_name = Path(s["note_path"]).name
    m = ops.move(s["doc_id"], "work", "claims", "inbox/2026")
    assert m["project"] == "claims" and m["folder"] == "inbox/2026"
    assert Path(m["note_path"]).name == note_name
    assert not (lib_vault / s["original_path"]).exists()
    assert not (lib_vault / s["note_path"]).exists()
    front, _ = notes.read_note(lib_vault / m["note_path"])
    assert front["project"] == "claims" and front["context"] == "work"
    u = ops.move(s["doc_id"], "personal", None, "")
    assert u["project"] is None
    assert "project" not in notes.read_note(lib_vault / u["note_path"])[0]


def test_move_clash_renames_original(lib_vault: Path):
    ops.upload("work", None, "", "a.pdf", "", b"one")
    s = ops.upload("work", None, "sub", "a.pdf", "", b"two")
    m = ops.move(s["doc_id"], "work", None, "")
    assert m["original"] == "a (2).pdf"


def test_move_rolls_back_when_note_write_fails(lib_vault: Path, monkeypatch):
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    def boom(path, text):
        raise OSError("disk full")
    monkeypatch.setattr(ops.notes, "write_atomic", boom)
    with pytest.raises(OSError):
        ops.move(s["doc_id"], "work", "payments", "")
    assert (lib_vault / s["original_path"]).read_bytes() == b"one"
    assert (lib_vault / s["note_path"]).exists()
    assert not (lib_vault / "20-contexts/work/projects/payments/docs/a.pdf").exists()


def test_move_into_archived_is_conflict(lib_vault: Path):
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    projects.update_project("work", "claims", archived=True)
    with pytest.raises(Conflict):
        ops.move(s["doc_id"], "work", "claims", "")


def test_rename_keeps_note_and_extension(lib_vault: Path):
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    r = ops.rename(s["doc_id"], "Payments API v3")
    assert r["title"] == "Payments API v3" and r["original"] == "Payments API v3.pdf"
    assert r["note_path"] == s["note_path"]
    assert ops.rename(s["doc_id"], "Same.pdf")["original"] == "Same.pdf"
    with pytest.raises(InvalidRequest):
        ops.rename(s["doc_id"], "a/b")


def test_delete_sends_both_files_to_trash(lib_vault: Path, monkeypatch):
    trashed = []
    monkeypatch.setattr(ops, "send2trash", lambda p: (trashed.append(Path(p).name), Path(p).unlink()))
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    ops.delete(s["doc_id"])
    assert sorted(trashed) == sorted(["a.pdf", Path(s["note_path"]).name])
    assert index.all_docs() == {}


def test_reindex_recovers_failed(lib_vault: Path, monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    assert s["index_status"] == "failed"
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "fixed")
    r = ops.reindex(s["doc_id"])
    assert r["index_status"] == "ok" and r["pages"] == 3
    assert notes.read_note(lib_vault / r["note_path"])[1].strip() == "fixed"
