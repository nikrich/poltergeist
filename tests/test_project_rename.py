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
