"""Companion-note format + the mtime-cached doc index and tree (spec §1–2)."""
from pathlib import Path

import pytest

from ghostbrain.api.repo.doc_library import index, notes
from ghostbrain.api.repo.doc_library.errors import NotFound
from tests.doc_library_helpers import lib_vault  # noqa: F401


def _seed(folder: Path, original: str, doc_id: str, *, project=None, status="ok", body="hello world"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / original).write_bytes(b"x")
    front = {
        "doc_id": doc_id, "source": notes.SOURCE, "title": Path(original).stem,
        "original": original, "kind": "pdf", "mime": "application/pdf", "size": 1,
        "sha256": "abc", "created": "2026-10-09T10:00:00+00:00", "context": "work",
        "index_status": status,
    }
    if project:
        front["project"] = project
    note = folder / notes.note_name(Path(original).stem, doc_id)
    notes.write_atomic(note, notes.render(front, body))
    return note


def test_note_roundtrip_and_naming(tmp_path: Path):
    assert notes.note_name("Payments API v2", "3f9a1c7b20de") == "payments-api-v2-3f9a1c.md"
    p = tmp_path / "n.md"
    notes.write_atomic(p, notes.render({"source": notes.SOURCE, "created": "2026-10-09T10:00:00+00:00"}, "body"))
    front, body = notes.read_note(p)
    assert front["created"] == "2026-10-09T10:00:00+00:00"  # stays a string
    assert body == "body\n"
    (tmp_path / "other.md").write_text("---\nsource: manual\n---\nx")
    assert notes.read_note(tmp_path / "other.md") is None


def test_unique_child_and_safe_filename(tmp_path: Path):
    (tmp_path / "a.pdf").write_bytes(b"")
    (tmp_path / "a (2).pdf").write_bytes(b"")
    assert notes.unique_child(tmp_path, "a.pdf").name == "a (3).pdf"
    assert notes.safe_filename("../../etc/passwd") == "passwd"
    assert notes.safe_filename(".env") == "env"
    assert notes.safe_filename("  ") == "untitled"
    assert notes.safe_filename("résumé.docx") == "résumé.docx"


def test_index_tree_and_attention(lib_vault: Path):
    proot = lib_vault / "20-contexts/work/projects/payments/docs"
    _seed(proot / "specs", "Payments API v2.pdf", "aaaaaaaaaaaa", project="payments")
    _seed(proot, "broken.pdf", "bbbbbbbbbbbb", project="payments", status="failed")
    orphan = _seed(proot, "gone.pdf", "cccccccccccc", project="payments")
    (proot / "gone.pdf").unlink()
    (proot / "specs" / "dropped-in.png").write_bytes(b"png")
    (proot / "empty").mkdir()
    index.invalidate()

    e = index.get("aaaaaaaaaaaa")
    assert e.folder == "specs" and e.project == "payments"
    s = index.summary(e)
    assert s["original_path"] == "20-contexts/work/projects/payments/docs/specs/Payments API v2.pdf"
    assert s["excerpt"] == "hello world"
    assert index.orphans() == {"cccccccccccc": orphan}
    kinds = sorted((a["kind"], a["name"]) for a in index.attention())
    assert kinds == [
        ("index_failed", "broken.pdf"),
        ("orphan_note", orphan.name),
        ("unclaimed_original", "dropped-in.png"),
    ]

    t = index.tree("work", "payments")
    assert len(t["scopes"]) == 1
    sc = t["scopes"][0]
    assert sc["name"] == "Payments" and sc["archived"] is False
    assert [f["name"] for f in sc["folders"]] == ["empty", "specs"]
    assert [d["doc_id"] for d in sc["docs"]] == ["bbbbbbbbbbbb"]
    assert [d["doc_id"] for d in sc["folders"][1]["docs"]] == ["aaaaaaaaaaaa"]
    assert len(t["attention"]) == 3

    with pytest.raises(NotFound):
        index.get("cccccccccccc")


def test_index_rebuilds_when_dirs_change(lib_vault: Path):
    root = lib_vault / "20-contexts/personal/docs"
    assert index.all_docs() == {}
    _seed(root, "late.pdf", "dddddddddddd")  # no explicit invalidate()
    assert "dddddddddddd" in index.all_docs()


def _note_with(folder: Path, name: str, front: dict, body: str = "x") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    notes.write_atomic(p, notes.render({"source": notes.SOURCE, **front}, body))
    return p


@pytest.mark.parametrize("bad_original", ["../../secret.pdf", "/etc/hosts"])
def test_original_must_be_bare_filename_inside_folder(lib_vault: Path, bad_original: str):
    proot = lib_vault / "20-contexts/work/projects/payments/docs"
    proot.mkdir(parents=True)
    (proot.parent.parent / "secret.pdf").write_bytes(b"x")  # outside the docs root
    note = _note_with(proot, "evil-aaaaaa.md", {
        "doc_id": "aaaaaaaaaaaa", "original": bad_original, "title": "evil",
        "kind": "pdf", "index_status": "ok",
    })
    index.invalidate()
    assert "aaaaaaaaaaaa" not in index.all_docs()
    assert index.orphans() == {"aaaaaaaaaaaa": note}
    assert {"kind": "orphan_note", "context": "work", "project": "payments",
            "folder": "", "name": note.name, "doc_id": "aaaaaaaaaaaa"} in index.attention()


def test_malformed_fields_do_not_break_tree(lib_vault: Path):
    proot = lib_vault / "20-contexts/work/projects/payments/docs"
    proot.mkdir(parents=True)
    (proot / "weird.pdf").write_bytes(b"x")
    _note_with(proot, "weird-bbbbbb.md", {
        "doc_id": "bbbbbbbbbbbb", "original": "weird.pdf", "title": ["odd"],
        "size": "abc", "pages": [1], "kind": {"a": 1}, "index_status": "ok",
    })
    index.invalidate()
    t = index.tree("work", "payments")
    (doc,) = t["scopes"][0]["docs"]
    assert doc["doc_id"] == "bbbbbbbbbbbb"
    assert doc["size"] == 0
    assert doc["pages"] is None


def test_duplicate_doc_id_second_note_becomes_orphan(lib_vault: Path):
    proot = lib_vault / "20-contexts/work/projects/payments/docs"
    _seed(proot / "a", "one.pdf", "eeeeeeeeeeee", project="payments")
    second = _seed(proot / "b", "two.pdf", "eeeeeeeeeeee", project="payments")
    index.invalidate()
    docs = index.all_docs()
    assert list(docs) == ["eeeeeeeeeeee"]
    assert docs["eeeeeeeeeeee"].folder == "a"
    assert index.orphans() == {"eeeeeeeeeeee": second}
    attn = index.attention()
    assert [a["kind"] for a in attn if a["name"] == second.name] == ["orphan_note"]
    assert {"kind": "unclaimed_original", "context": "work", "project": "payments",
            "folder": "b", "name": "two.pdf", "doc_id": None} in attn
