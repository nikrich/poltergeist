"""Full project rename: folder move, re-stamp, link rewrite, chats, rollback."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghostbrain.api.repo import projects


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    (v / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(tmp_path / "chats"))
    projects.create_project("work", "Paymnets")
    projects.create_project("work", "Pay")
    return v


def _note(path: Path, front: dict, body: str = "body") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{yaml.safe_dump(front, sort_keys=False)}---\n\n{body}\n", encoding="utf-8")


def _front(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---\n")[1])


OLD = "20-contexts/work/projects/paymnets"
NEW = "20-contexts/work/projects/payments"


def test_same_slug_rename_only_updates_registry(vault: Path):
    p = projects.rename_project("work", "paymnets", name="PAYMNETS", description="d")
    assert p["slug"] == "paymnets" and p["name"] == "PAYMNETS" and p["description"] == "d"
    assert (vault / OLD).is_dir()


def test_full_rename_moves_restamps_and_rewrites(vault: Path):
    _note(vault / OLD / "manual-1-jot.md", {"id": "j1", "project": "paymnets", "context": "work"})
    _note(vault / OLD / "docs/specs/spec-aaaaaa.md", {"doc_id": "aaaaaaaaaaaa", "source": "doc-library",
          "original": "Spec.pdf", "project": "paymnets", "context": "work"})
    (vault / OLD / "docs/specs/Spec.pdf").write_bytes(b"%PDF")
    _note(vault / "20-contexts/personal/elsewhere.md", {"id": "e"},
          f"see [[{OLD}/manual-1-jot.md|the jot]] and [[{OLD}]] but not paymnets prose "
          f"or [[20-contexts/work/projects/pay/x.md]]")
    _note(vault / ".trash/old.md", {}, f"[[{OLD}/manual-1-jot.md]]")
    _note(vault / OLD / "self.md", {"project": "paymnets"}, f"[[{OLD}/manual-1-jot.md]]")
    p = projects.rename_project("work", "paymnets", name="Payments")
    assert p["slug"] == "payments" and p["id"] == "work/payments" and p["name"] == "Payments"
    assert f"[[{OLD}/manual-1-jot.md]]" in (vault / ".trash/old.md").read_text()
    assert f"[[{NEW}/manual-1-jot.md]]" in (vault / NEW / "self.md").read_text()
    assert not (vault / OLD).exists()
    assert (vault / NEW / "docs/specs/Spec.pdf").read_bytes() == b"%PDF"
    assert _front(vault / NEW / "manual-1-jot.md")["project"] == "payments"
    assert _front(vault / NEW / "docs/specs/spec-aaaaaa.md")["project"] == "payments"
    other = (vault / "20-contexts/personal/elsewhere.md").read_text()
    assert f"[[{NEW}/manual-1-jot.md|the jot]]" in other and f"[[{NEW}]]" in other
    assert "paymnets prose" in other
    assert "[[20-contexts/work/projects/pay/x.md]]" in other
    assert projects.get_project("work", "paymnets") is None
    assert projects.get_project("work", "payments")["name"] == "Payments"


def test_notes_stamped_with_another_project_keep_their_stamp(vault: Path):
    _note(vault / OLD / "odd.md", {"project": "something-else"})
    projects.rename_project("work", "paymnets", name="Payments")
    assert _front(vault / NEW / "odd.md")["project"] == "something-else"


def test_collision_is_rejected_without_changes(vault: Path):
    _note(vault / OLD / "a.md", {"project": "paymnets"})
    with pytest.raises(projects.ProjectExists):
        projects.rename_project("work", "paymnets", name="Pay")
    assert (vault / OLD / "a.md").exists()
    (vault / NEW).mkdir(parents=True)  # stray unregistered folder also blocks
    with pytest.raises(projects.ProjectExists):
        projects.rename_project("work", "paymnets", name="Payments")
    assert (vault / OLD / "a.md").exists()
    assert projects.get_project("work", "paymnets") is not None


def test_blank_name_is_rejected(vault: Path):
    with pytest.raises(ValueError):
        projects.rename_project("work", "paymnets", name="   ")
    assert projects.get_project("work", "paymnets")["name"] == "Paymnets"


def test_failure_midway_rolls_back(vault: Path, monkeypatch):
    for i in range(4):
        _note(vault / OLD / f"n{i}.md", {"project": "paymnets", "updated": "2026-01-01T00:00:00+00:00"})
    (vault / OLD / "blob.bin").write_bytes(b"\x00\x01")
    _note(vault / "20-contexts/personal/l.md", {}, f"[[{OLD}/n0.md]]")
    before = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    from ghostbrain import vault_write
    real = vault_write.write
    calls = {"n": 0}

    def flaky(rel, **kw):
        if kw.get("op") == "move":
            calls["n"] += 1
            if calls["n"] == 3:
                raise OSError("disk full")
        return real(rel, **kw)

    monkeypatch.setattr(projects.vault_write, "write", flaky)
    with pytest.raises(OSError):
        projects.rename_project("work", "paymnets", name="Payments")
    assert sorted(p.name for p in (vault / OLD).glob("*.md")) == ["n0.md", "n1.md", "n2.md", "n3.md"]
    assert all(_front(vault / OLD / f"n{i}.md")["project"] == "paymnets" for i in range(4))
    assert not (vault / NEW).exists() or not any((vault / NEW).rglob("*.md"))
    assert f"[[{OLD}/n0.md]]" in (vault / "20-contexts/personal/l.md").read_text()
    assert projects.get_project("work", "paymnets") is not None
    after = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    assert after == before  # byte-for-byte, incl. `updated` and the binary file


def test_failure_in_registry_write_rolls_back_links_and_chats(vault: Path, monkeypatch):
    from ghostbrain.api.repo import chat_store
    _note(vault / OLD / "n.md", {"project": "paymnets"})
    _note(vault / "20-contexts/personal/l.md", {}, f"[[{OLD}/n.md]]")
    conv = chat_store.create()
    chat_store.update(conv["id"], project="work/paymnets")
    before = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}

    def boom(items):
        raise OSError("registry write failed")

    monkeypatch.setattr(projects, "_write", boom)
    with pytest.raises(OSError):
        projects.rename_project("work", "paymnets", name="Payments")
    assert {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()} == before
    assert not (vault / NEW).exists()
    assert chat_store.get(conv["id"])["project"] == "work/paymnets"


def test_chat_conversations_are_repointed(vault: Path):
    from ghostbrain.api.repo import chat_store
    conv = chat_store.create()
    chat_store.update(conv["id"], project="work/paymnets")
    projects.rename_project("work", "paymnets", name="Payments")
    assert chat_store.get(conv["id"])["project"] == "work/payments"


def test_unarchive_and_unknown(vault: Path):
    projects.update_project("work", "pay", archived=True)
    assert projects.rename_project("work", "pay", archived=False)["archived"] is False
    assert projects.rename_project("work", "ghost", name="X") is None


# --- fix round 1 -------------------------------------------------------------


def test_concurrent_edit_during_link_rewrite_wins(vault: Path, monkeypatch):
    """A note edited between the rename's read and its write keeps the user's edit."""
    racy = vault / "20-contexts/personal/racy.md"
    calm = vault / "20-contexts/personal/calm.md"
    _note(racy, {}, f"[[{OLD}/a.md]]")
    _note(calm, {}, f"[[{OLD}/a.md]]")
    real = projects.vault_write.write
    raced = {"done": False}

    def racing(rel, **kw):
        if kw.get("op") == "modify" and rel.endswith("racy.md") and not raced["done"]:
            raced["done"] = True
            racy.write_text("user typed this meanwhile\n", encoding="utf-8")
        return real(rel, **kw)

    monkeypatch.setattr(projects.vault_write, "write", racing)
    p = projects.rename_project("work", "paymnets", name="Payments")
    assert p["slug"] == "payments"
    assert raced["done"]
    assert racy.read_text(encoding="utf-8") == "user typed this meanwhile\n"
    assert f"[[{NEW}/a.md]]" in calm.read_text(encoding="utf-8")


def test_rollback_does_not_clobber_edit_made_after_rewrite(vault: Path, monkeypatch):
    """Undo of a link rewrite is skipped when the note changed after the rename wrote it."""
    edited = vault / "20-contexts/personal/edited.md"
    _note(edited, {}, f"[[{OLD}/a.md]]")
    real_write = projects._write

    def edit_then_fail(items):
        edited.write_text("user edit after rewrite\n", encoding="utf-8")
        raise OSError("registry write failed")

    monkeypatch.setattr(projects, "_write", edit_then_fail)
    with pytest.raises(OSError):
        projects.rename_project("work", "paymnets", name="Payments")
    monkeypatch.setattr(projects, "_write", real_write)
    assert edited.read_text(encoding="utf-8") == "user edit after rewrite\n"
    assert projects.get_project("work", "paymnets") is not None


def test_prefix_siblings_are_not_rewritten(vault: Path):
    projects.create_project("work", "Payments")
    links = vault / "20-contexts/personal/links.md"
    _note(links, {}, (
        "[[20-contexts/work/projects/paymnets/a.md]] "
        "[[20-contexts/work/projects/payments/b.md]] "
        "[[20-contexts/work/projects/pay/c.md]] "
        "[[20-contexts/work/projects/pay]]"
    ))
    projects.rename_project("work", "pay", name="Paid")
    text = links.read_text(encoding="utf-8")
    assert "[[20-contexts/work/projects/paymnets/a.md]]" in text
    assert "[[20-contexts/work/projects/payments/b.md]]" in text
    assert "[[20-contexts/work/projects/paid/c.md]]" in text
    assert "[[20-contexts/work/projects/paid]]" in text
    assert "projects/pay/" not in text and "projects/pay]" not in text


def _doc(vault: Path, doc_id: str) -> None:
    _note(vault / OLD / "docs" / f"spec-{doc_id[:6]}.md",
          {"doc_id": doc_id, "source": "doc-library", "original": "Spec.pdf",
           "project": "paymnets", "context": "work", "index_status": "ok"})
    (vault / OLD / "docs" / "Spec.pdf").write_bytes(b"%PDF")


def test_busy_while_doc_is_indexing(vault: Path):
    from ghostbrain.api.repo.doc_library import index
    _doc(vault, "bbbbbbbbbbbb")
    index.mark_active("bbbbbbbbbbbb")
    try:
        with pytest.raises(projects.ProjectBusy):
            projects.rename_project("work", "paymnets", name="Payments")
    finally:
        index.unmark_active("bbbbbbbbbbbb")
    assert (vault / OLD / "docs" / "spec-bbbbbb.md").exists()
    assert not (vault / NEW).exists()
    assert projects.rename_project("work", "paymnets", name="Payments")["slug"] == "payments"


def test_busy_while_upload_has_no_note_yet(vault: Path):
    """An upload is marked active before its note exists — its project is unknown, so refuse."""
    from ghostbrain.api.repo.doc_library import index
    index.mark_active("cccccccccccc")
    try:
        with pytest.raises(projects.ProjectBusy):
            projects.rename_project("work", "paymnets", name="Payments")
    finally:
        index.unmark_active("cccccccccccc")


def test_busy_while_doc_is_summarising(vault: Path, monkeypatch):
    from ghostbrain.api.repo.doc_library import ai_summary
    _doc(vault, "dddddddddddd")
    monkeypatch.setattr(ai_summary, "is_summarising", lambda doc_id: doc_id == "dddddddddddd")
    with pytest.raises(projects.ProjectBusy) as exc:
        projects.rename_project("work", "paymnets", name="Payments")
    assert not isinstance(exc.value, projects.ProjectExists)
    assert not (vault / NEW).exists()


def test_busy_elsewhere_does_not_block(vault: Path, monkeypatch):
    from ghostbrain.api.repo.doc_library import ai_summary
    _note(vault / "20-contexts/work/projects/pay/docs/other-eeeeee.md",
          {"doc_id": "eeeeeeeeeeee", "source": "doc-library", "original": "O.pdf",
           "project": "pay", "context": "work", "index_status": "ok"})
    (vault / "20-contexts/work/projects/pay/docs/O.pdf").write_bytes(b"%PDF")
    monkeypatch.setattr(ai_summary, "is_summarising", lambda doc_id: doc_id == "eeeeeeeeeeee")
    assert projects.rename_project("work", "paymnets", name="Payments")["slug"] == "payments"


def test_file_left_in_old_dir_keeps_dir_and_succeeds(vault: Path, monkeypatch, caplog):
    _note(vault / OLD / "a.md", {"project": "paymnets"})
    real = projects.vault_write.write

    def worker_files_late(rel, **kw):
        out = real(rel, **kw)
        if kw.get("op") == "move" and not (vault / OLD / "late.md").exists():
            _note(vault / OLD / "late.md", {"project": "paymnets"})
        return out

    monkeypatch.setattr(projects.vault_write, "write", worker_files_late)
    with caplog.at_level("WARNING", logger="ghostbrain.projects"):
        p = projects.rename_project("work", "paymnets", name="Payments")
    assert p["slug"] == "payments"
    assert (vault / OLD / "late.md").exists()
    assert (vault / NEW / "a.md").exists()
    assert any("left in" in r.getMessage() for r in caplog.records)


def test_old_dir_cleanup_error_does_not_fail_rename(vault: Path, monkeypatch):
    def boom(d):
        raise OSError("permission denied")

    monkeypatch.setattr(projects, "_rmdir_tree_if_empty", boom)
    p = projects.rename_project("work", "paymnets", name="Payments")
    assert p["slug"] == "payments"
    assert projects.get_project("work", "payments") is not None


@pytest.mark.parametrize("bad", ["!!!", "—", "  ...  "])
def test_name_without_alphanumerics_is_rejected(vault: Path, bad: str):
    with pytest.raises(ValueError):
        projects.rename_project("work", "paymnets", name=bad)
    assert projects.get_project("work", "paymnets")["name"] == "Paymnets"


def test_link_scan_matches_uppercase_md_and_skips_dot_dirs(vault: Path):
    upper = vault / "20-contexts/personal/UPPER.MD"
    upper.parent.mkdir(parents=True, exist_ok=True)
    upper.write_text(f"[[{OLD}/a.md]]\n", encoding="utf-8")
    hidden = vault / ".obsidian/deep/x.md"
    _note(hidden, {}, f"[[{OLD}/a.md]]")
    projects.rename_project("work", "paymnets", name="Payments")
    assert f"[[{NEW}/a.md]]" in upper.read_text(encoding="utf-8")
    assert f"[[{OLD}/a.md]]" in hidden.read_text(encoding="utf-8")


def test_rollback_moves_back_self_linked_note_without_trailing_newline(vault: Path, monkeypatch):
    """Rollback restores the link rewrite first, then moves the note back — even when
    the restore cannot be byte-identical (vault_write appends a final newline)."""
    note = vault / OLD / "self.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(f"---\nproject: paymnets\n---\n\n[[{OLD}/self.md]]", encoding="utf-8")

    def boom(items):
        raise OSError("registry write failed")

    monkeypatch.setattr(projects, "_write", boom)
    with pytest.raises(OSError):
        projects.rename_project("work", "paymnets", name="Payments")
    assert note.exists()
    assert _front(note)["project"] == "paymnets"
    assert f"[[{OLD}/self.md]]" in note.read_text(encoding="utf-8")
    assert not (vault / NEW).exists()


def test_malformed_note_aborts_rename_naming_the_note(vault: Path, monkeypatch):
    from ghostbrain import vault_write
    from ghostbrain.vault_write import MalformedNote

    _note(vault / OLD / "a.md", {"project": "paymnets"})
    _note(vault / OLD / "b.md", {"project": "paymnets"})
    _note(vault / "20-contexts/personal/l.md", {}, f"[[{OLD}/a.md]]")
    before = {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()}
    real_write = vault_write.write

    def flaky(rel, **kw):
        if rel == f"{OLD}/b.md" and kw.get("op") == "move":
            raise MalformedNote("field 'project' did not round-trip through YAML")
        return real_write(rel, **kw)

    monkeypatch.setattr(vault_write, "write", flaky)
    with pytest.raises(projects.MalformedProjectNote) as exc:
        projects.rename_project("work", "paymnets", name="Payments")
    assert exc.value.path == f"{OLD}/b.md"
    assert str(exc.value) == f"can't rename: {OLD}/b.md has malformed frontmatter"
    assert {p: p.read_bytes() for p in vault.rglob("*") if p.is_file()} == before
    assert not (vault / NEW).exists()
    assert projects.get_project("work", "paymnets") is not None


def test_concurrent_renames_of_different_projects_both_land(vault: Path, monkeypatch):
    import threading
    import time

    real_write = projects._write

    def slow_write(items):
        time.sleep(0.2)  # widen the registry read-modify-write window
        real_write(items)

    monkeypatch.setattr(projects, "_write", slow_write)
    errors: list[BaseException] = []

    def run(slug: str, name: str) -> None:
        try:
            projects.rename_project("work", slug, name=name)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [
        threading.Thread(target=run, args=("paymnets", "Payments")),
        threading.Thread(target=run, args=("pay", "Payroll")),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not errors
    slugs = {p["slug"] for p in projects.list_projects(include_archived=True)}
    assert slugs == {"payments", "payroll"}
    assert (vault / NEW).is_dir() and (vault / "20-contexts/work/projects/payroll").is_dir()


def test_same_slug_edit_under_lock_does_not_deadlock(vault: Path):
    with projects._registry_lock:  # reentrant: rename → update_project
        p = projects.rename_project("work", "paymnets", name="PAYMNETS", description="x")
    assert p["description"] == "x"


def test_md_library_original_keeps_its_bytes(vault: Path):
    """An uploaded .md original is byte-identical to the upload (sha256 dedupe):
    neither the link rewrite nor the re-stamp may touch it."""
    docs = vault / OLD / "docs"
    original = (
        f"---\nproject: paymnets\n---\n\n# Readme\n\nsee [[{OLD}/manual-1-jot.md]]\n"
    ).encode()
    docs.mkdir(parents=True)
    (docs / "Readme.md").write_bytes(original)
    _note(docs / "readme-aaaaaa.md", {"doc_id": "aaaaaaaaaaaa", "source": "doc-library",
          "original": "Readme.md", "project": "paymnets", "context": "work"})
    _note(vault / OLD / "manual-1-jot.md", {"project": "paymnets"})
    # An original elsewhere in the vault that mentions the project is left alone too.
    other_docs = vault / "20-contexts/personal/docs"
    other = f"links to [[{OLD}/manual-1-jot.md]]\n".encode()
    other_docs.mkdir(parents=True)
    (other_docs / "Notes.md").write_bytes(other)
    _note(other_docs / "notes-bbbbbb.md", {"doc_id": "bbbbbbbbbbbb", "source": "doc-library",
          "original": "Notes.md", "context": "personal"})

    projects.rename_project("work", "paymnets", name="Payments")

    assert (vault / NEW / "docs/Readme.md").read_bytes() == original
    assert (other_docs / "Notes.md").read_bytes() == other
    assert _front(vault / NEW / "docs/readme-aaaaaa.md")["project"] == "payments"
    assert _front(vault / NEW / "manual-1-jot.md")["project"] == "payments"
