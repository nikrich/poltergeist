"""Folder create / move / delete-empty (spec §2)."""
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import folders, index, notes, ops
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidPath, InvalidRequest, NotFound
from tests.doc_library_helpers import lib_vault  # noqa: F401

W = "20-contexts/work/docs"


@pytest.fixture(autouse=True)
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body")


def test_create_with_keep_and_conflict(lib_vault: Path):
    assert folders.create("work", None, "specs/v2") == {"context": "work", "project": None, "path": "specs/v2"}
    assert (lib_vault / W / "specs/v2/.keep").exists()
    with pytest.raises(Conflict):
        folders.create("work", None, "specs/v2")
    with pytest.raises(InvalidRequest):
        folders.create("work", None, "")
    with pytest.raises(InvalidPath):
        folders.create("work", None, "../x")


def test_rename_within_scope(lib_vault: Path):
    folders.create("work", None, "a")
    folders.move(("work", None, "a"), ("work", None, "b/c"))
    assert (lib_vault / W / "b/c").is_dir() and not (lib_vault / W / "a").exists()


def test_move_across_projects_restamps_notes(lib_vault: Path):
    s = ops.upload("work", "payments", "specs/deep", "a.pdf", "", b"a")
    folders.move(("work", "payments", "specs"), ("work", "claims", "from-payments"))
    e = index.get(s["doc_id"])
    assert e.project == "claims" and e.folder == "from-payments/deep"
    assert notes.read_note(e.note)[0]["project"] == "claims"


def test_move_guards(lib_vault: Path):
    folders.create("work", None, "a/b")
    folders.create("work", None, "x")
    with pytest.raises(InvalidRequest):
        folders.move(("work", None, "a"), ("work", None, "a/b/inside"))
    with pytest.raises(Conflict):
        folders.move(("work", None, "a"), ("work", None, "x"))
    with pytest.raises(NotFound):
        folders.move(("work", None, "nope"), ("work", None, "y"))
    with pytest.raises(InvalidRequest):
        folders.move(("work", None, ""), ("work", None, "y"))
    projects.update_project("work", "claims", archived=True)
    with pytest.raises(Conflict):
        folders.move(("work", None, "x"), ("work", "claims", "x"))


def test_delete_only_empty(lib_vault: Path):
    folders.create("work", None, "empty")
    folders.delete("work", None, "empty")
    assert not (lib_vault / W / "empty").exists()
    ops.upload("work", None, "full", "a.pdf", "", b"a")
    with pytest.raises(Conflict):
        folders.delete("work", None, "full")
    with pytest.raises(NotFound):
        folders.delete("work", None, "ghost")
