"""Upload pipeline (spec §2): original + companion note, dedupe, clashes, failure keeps file."""
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import index, notes, ops
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidPath, TooLarge
from tests.doc_library_helpers import lib_vault  # noqa: F401

PROOT = "20-contexts/work/projects/payments/docs"


@pytest.fixture
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda name, mime, src: f"text of {name}")
    monkeypatch.setattr(ops, "_pdf_pages", lambda path: 24)


def test_upload_pdf_writes_original_and_note(lib_vault: Path, fake_extract):
    s = ops.upload("work", "payments", "specs", "Payments API v2.pdf", "application/pdf", b"%PDF-1")
    folder = lib_vault / PROOT / "specs"
    assert (folder / "Payments API v2.pdf").read_bytes() == b"%PDF-1"
    note = folder / notes.note_name("Payments API v2", s["doc_id"])
    front, body = notes.read_note(note)
    assert front["kind"] == "pdf" and front["pages"] == 24 and front["project"] == "payments"
    assert front["index_status"] == "ok" and len(front["doc_id"]) == 12
    assert body.strip() == "text of Payments API v2.pdf"
    assert s["title"] == "Payments API v2" and s["duplicate"] is False and s["folder"] == "specs"


def test_upload_kinds(lib_vault: Path, fake_extract):
    img = ops.upload("work", None, "", "flow.png", "image/png", b"\x89PNG")
    assert notes.read_note(lib_vault / img["note_path"])[1].strip() == "a diagram"
    md = ops.upload("work", None, "", "runbook.md", "", b"# Runbook")
    assert notes.read_note(lib_vault / md["note_path"])[1].strip() == "# Runbook"
    z = ops.upload("work", None, "", "bundle.zip", "application/zip", b"PK")
    assert z["kind"] == "opaque" and z["index_status"] == "ok"
    assert notes.read_note(lib_vault / z["note_path"])[1].strip() == ""


def test_duplicate_same_scope_returns_existing_other_scope_is_new(lib_vault: Path, fake_extract):
    a = ops.upload("work", "payments", "", "a.pdf", "", b"same")
    again = ops.upload("work", "payments", "other", "renamed.pdf", "", b"same")
    assert again["duplicate"] is True and again["doc_id"] == a["doc_id"]
    assert not (lib_vault / PROOT / "other").exists()
    b = ops.upload("work", "claims", "", "a.pdf", "", b"same")
    assert b["duplicate"] is False and b["doc_id"] != a["doc_id"]
    assert Path(b["note_path"]).name != Path(a["note_path"]).name


def test_name_clash_gets_suffix(lib_vault: Path, fake_extract):
    ops.upload("work", None, "", "a.pdf", "", b"one")
    s = ops.upload("work", None, "", "a.pdf", "", b"two")
    assert s["original"] == "a (2).pdf"


def test_hostile_filename_stays_in_folder(lib_vault: Path, fake_extract):
    s = ops.upload("work", None, "x", "../../evil.pdf", "", b"e")
    assert s["original_path"] == "20-contexts/work/docs/x/evil.pdf"
    with pytest.raises(InvalidPath):
        ops.upload("work", None, "../escape", "a.pdf", "", b"e")


def test_extraction_failure_keeps_original(lib_vault: Path, monkeypatch):
    def boom(*a):
        raise RuntimeError("corrupt")
    monkeypatch.setattr(ops.attachment_extract, "extract_text", boom)
    s = ops.upload("work", None, "", "bad.pdf", "", b"%PDF-broken")
    assert s["index_status"] == "failed"
    assert (lib_vault / s["original_path"]).read_bytes() == b"%PDF-broken"


def test_limits_and_archived(lib_vault: Path, fake_extract):
    with pytest.raises(TooLarge):
        ops.upload("work", None, "", "big.txt", "", b"x" * 1_000_001)
    projects.update_project("work", "claims", archived=True)
    with pytest.raises(Conflict):
        ops.upload("work", "claims", "", "a.pdf", "", b"x")
    assert index.all_docs() == {}
