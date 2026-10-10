"""Needs-attention repairs: adopt unclaimed originals, remove orphan notes."""
from pathlib import Path

import pytest

from ghostbrain.api.repo.doc_library import index, ops
from ghostbrain.api.repo.doc_library.errors import Conflict, NotFound
from tests.doc_library_helpers import lib_vault  # noqa: F401


@pytest.fixture(autouse=True)
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body")


def test_adopt_unclaimed_original(lib_vault: Path):
    d = lib_vault / "20-contexts/work/docs/inbox"
    d.mkdir(parents=True)
    (d / "Dropped.pdf").write_bytes(b"%PDF")
    index.invalidate()
    assert [a["kind"] for a in index.attention()] == ["unclaimed_original"]
    s = ops.adopt("work", None, "inbox", "Dropped.pdf")
    assert s["title"] == "Dropped" and s["kind"] == "pdf" and s["folder"] == "inbox"
    assert index.attention() == []
    with pytest.raises(Conflict):
        ops.adopt("work", None, "inbox", "Dropped.pdf")
    with pytest.raises(NotFound):
        ops.adopt("work", None, "inbox", "missing.pdf")


def test_remove_orphan(lib_vault: Path, monkeypatch):
    s = ops.upload("work", None, "", "a.pdf", "", b"a")
    (lib_vault / s["original_path"]).unlink()
    index.invalidate()
    assert list(index.orphans()) == [s["doc_id"]]
    trashed = []
    monkeypatch.setattr(ops, "send2trash", lambda p: (trashed.append(p), Path(p).unlink()))
    ops.remove_orphan(s["doc_id"])
    assert index.orphans() == {} and len(trashed) == 1
    with pytest.raises(NotFound):
        ops.remove_orphan(s["doc_id"])
