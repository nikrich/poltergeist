"""vault_write.write — ops, etags, atomicity, locking (spec B1)."""
from __future__ import annotations

import os
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from ghostbrain import vault_write
from ghostbrain.vault_write import (
    ASSISTANT,
    DELETE_FIELD,
    MCP,
    USER,
    FileMissing,
    InvalidPath,
    WriteConflict,
    compute_etag,
    current_etag,
    normalize_if_match,
    parse_actor,
    plugin_actor,
    read,
    worker_actor,
    write,
    write_new,
)
from ghostbrain.vault_write import writer

NOW = "2026-10-09T10:00:00+00:00"
NOTE = (
    "---\n"
    "# keep me\n"
    "title: \"Odd: quoting\"\n"
    "zeta: 1\n"
    "updated: '2026-01-01T00:00:00+00:00'\n"
    "---\n"
    "\n"
    "old body\n"
)


@pytest.fixture
def vw_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(writer, "_now_iso", lambda: NOW)
    return vault


def _put(vault: Path, rel: str, text: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))
    return p


# ── actor / etag helpers ─────────────────────────────────────────────────

def test_actor_helpers():
    assert USER == "user" and ASSISTANT == "assistant" and MCP == "mcp"
    assert plugin_actor("familiar") == "plugin:familiar"
    assert worker_actor("jot-router") == "worker:jot-router"
    for bad in ("", "admin", "plugin:", "plugin:../x", "worker:a b", "User"):
        with pytest.raises(ValueError):
            parse_actor(bad)


def test_compute_etag_and_normalize_if_match():
    assert compute_etag(b"abc") == "ba7816bf8f01cfea"
    assert len(compute_etag(b"")) == 16
    assert normalize_if_match('"ba7816bf8f01cfea"') == "ba7816bf8f01cfea"
    assert normalize_if_match('W/"ba7816bf8f01cfea"') == "ba7816bf8f01cfea"
    assert normalize_if_match("ba7816bf8f01cfea") == "ba7816bf8f01cfea"
    assert normalize_if_match(None) is None
    assert normalize_if_match("") is None
    assert normalize_if_match("*") is None


# ── path guard ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", ["", "/etc/x.md", "../x.md", "a/../../x.md", "x.sh", "a\x00.md"])
def test_rejects_unsafe_paths(vw_vault, rel):
    with pytest.raises(InvalidPath):
        write(rel, content="x", op="create", actor=USER)


def test_invalid_actor_and_bad_arg_combinations(vw_vault):
    with pytest.raises(ValueError):
        write("a.md", content="x", op="create", actor="admin")
    with pytest.raises(ValueError):
        write("a.md", content="x", body="y", actor=USER)
    with pytest.raises(ValueError):
        write("a.md", op="move", actor=USER)
    with pytest.raises(ValueError):
        write("a.md", actor=USER)  # modify with nothing to do
    with pytest.raises(ValueError):
        write("a.md", body="x", op="create", actor=USER)


# ── create ───────────────────────────────────────────────────────────────

def test_create_md_adds_trailing_newline(vw_vault):
    res = write("20-contexts/work/notes/a.md", content="# A", op="create", actor=USER)
    p = vw_vault / "20-contexts/work/notes/a.md"
    assert p.read_bytes() == b"# A\n"
    assert res.status == "applied" and res.change_id is None
    assert res.etag == compute_etag(b"# A\n")
    assert res.path == "20-contexts/work/notes/a.md"


def test_create_html_is_verbatim(vw_vault):
    write("docs/a.html", content="<p>x</p>", op="create", actor=MCP)
    assert (vw_vault / "docs/a.html").read_bytes() == b"<p>x</p>"


def test_create_over_existing_conflicts(vw_vault):
    p = _put(vw_vault, "a.md", "old\n")
    with pytest.raises(WriteConflict) as ei:
        write("a.md", content="new", op="create", actor=USER)
    assert ei.value.current_etag == compute_etag(b"old\n")
    assert p.read_text() == "old\n"


def test_new_file_mode_is_0644(vw_vault):
    if sys.platform == "win32":
        pytest.skip("POSIX permissions")
    write("a.md", content="x", op="create", actor=USER)
    assert stat.S_IMODE((vw_vault / "a.md").stat().st_mode) == 0o644


def test_write_new_suffixes_instead_of_overwriting(vw_vault):
    _put(vw_vault, "d/x.html", "first")
    res2 = write_new("d/x.html", "second", actor=MCP)
    res3 = write_new("d/x.html", "third", actor=MCP)
    assert res2.path == "d/x-2.html" and res3.path == "d/x-3.html"
    assert (vw_vault / "d/x.html").read_text() == "first"


# ── modify: body splice ──────────────────────────────────────────────────

def test_body_save_keeps_frontmatter_bytes_and_bumps_only_updated(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    res = write("n.md", body="new body", actor=USER)
    out = p.read_text()
    assert out == NOTE.replace("2026-01-01T00:00:00+00:00", NOW).replace("old body", "new body")
    assert res.updated == NOW
    assert res.etag == compute_etag(p.read_bytes())


def test_body_save_without_updated_key_does_not_invent_it(vw_vault):
    p = _put(vw_vault, "n.md", "---\nsource: manual\n---\n\nbody\n")
    res = write("n.md", body="rewritten", actor=USER)
    assert p.read_text() == "---\nsource: manual\n---\n\nrewritten\n"
    assert res.updated is None


def test_body_save_on_invalid_yaml_skips_bump_and_keeps_bytes(vw_vault):
    broken = "---\ntitle: [unclosed\nupdated: '2026-01-01T00:00:00+00:00'\n---\n\nold\n"
    p = _put(vw_vault, "n.md", broken)
    res = write("n.md", body="new", actor=USER)
    assert p.read_text() == broken.replace("old\n", "new\n")
    assert res.updated is None


def test_identical_write_does_not_touch_the_file(vw_vault):
    p = _put(vw_vault, "n.md", "---\nsource: manual\n---\n\nsame\n")
    before = p.stat().st_mtime_ns
    time.sleep(0.01)
    res = write("n.md", body="same", actor=USER)
    assert p.stat().st_mtime_ns == before
    assert res.etag == compute_etag(p.read_bytes())


# ── etag precondition ────────────────────────────────────────────────────

def test_matching_base_etag_applies(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    write("n.md", body="x", actor=USER, base_etag=compute_etag(NOTE.encode()))
    assert "x\n" in p.read_text()


def test_stale_base_etag_conflicts_and_leaves_file(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    with pytest.raises(WriteConflict) as ei:
        write("n.md", body="x", actor=ASSISTANT, base_etag="0000000000000000")
    assert ei.value.current_etag == compute_etag(NOTE.encode())
    assert p.read_text() == NOTE


def test_base_etag_on_missing_file_conflicts(vw_vault):
    with pytest.raises(WriteConflict) as ei:
        write("gone.md", body="x", actor=USER, base_etag="0000000000000000")
    assert ei.value.current_etag is None


def test_modify_missing_file_raises_file_missing(vw_vault):
    with pytest.raises(FileMissing):
        write("gone.md", body="x", actor=USER)


# ── fields / delete / move ───────────────────────────────────────────────

def test_fields_edit_explicit_updated_wins(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    res = write("n.md", fields={"zeta": 2, "updated": "2026-02-02T00:00:00+00:00"}, actor=USER)
    out = p.read_text()
    assert "zeta: 2\n" in out and "updated: '2026-02-02T00:00:00+00:00'\n" in out
    assert res.updated == "2026-02-02T00:00:00+00:00"
    assert "# keep me\n" in out


def test_delete(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    res = write("n.md", op="delete", actor=USER)
    assert not p.exists() and res.etag is None


def test_move_with_fields_and_project_delete(vw_vault):
    _put(vw_vault, "inbox/j.md", "---\nproject: old\ncontext: null\n---\n\nb\n")
    res = write(
        "inbox/j.md", op="move", dest="ctx/work/j.md",
        fields={"context": "work", "project": DELETE_FIELD}, actor=worker_actor("jot-router"),
    )
    assert not (vw_vault / "inbox/j.md").exists()
    assert (vw_vault / "ctx/work/j.md").read_text() == "---\ncontext: work\n---\n\nb\n"
    assert res.path == "ctx/work/j.md"


def test_move_onto_existing_destination_conflicts(vw_vault):
    _put(vw_vault, "a.md", "a\n")
    _put(vw_vault, "b.md", "b\n")
    with pytest.raises(WriteConflict):
        write("a.md", op="move", dest="b.md", actor=USER)
    assert (vw_vault / "a.md").read_text() == "a\n"
    assert (vw_vault / "b.md").read_text() == "b\n"


# ── atomicity / permissions / locking ────────────────────────────────────

def test_failed_replace_leaves_original_and_no_temp_files(vw_vault, monkeypatch):
    p = _put(vw_vault, "n.md", NOTE)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(writer.os, "replace", boom)
    with pytest.raises(OSError):
        write("n.md", body="x", actor=USER)
    assert p.read_text() == NOTE
    assert [f.name for f in vw_vault.iterdir()] == ["n.md"]


def test_existing_permissions_are_preserved(vw_vault):
    if sys.platform == "win32":
        pytest.skip("POSIX permissions")
    p = _put(vw_vault, "n.md", NOTE)
    p.chmod(0o640)
    write("n.md", body="x", actor=USER)
    assert stat.S_IMODE(p.stat().st_mode) == 0o640


def test_concurrent_field_edits_never_lose_updates(vw_vault, monkeypatch):
    p = _put(vw_vault, "n.md", "---\ntitle: a\n---\n\nbody\n")
    real_read = writer._read_bytes

    def slow_read(path):
        data = real_read(path)
        time.sleep(0.005)  # widen the read→write window a missing lock would lose
        return data

    monkeypatch.setattr(writer, "_read_bytes", slow_read)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: write("n.md", fields={f"k{i}": i}, actor=USER), range(16)))
    meta = yaml.safe_load(p.read_text().split("---\n")[1])
    assert all(meta[f"k{i}"] == i for i in range(16))


# ── read / current_etag ──────────────────────────────────────────────────

def test_read_snapshot_and_current_etag(vw_vault):
    _put(vw_vault, "n.md", NOTE)
    snap = read("n.md")
    assert snap.etag == compute_etag(NOTE.encode())
    assert snap.body == "old body"
    assert snap.metadata()["title"] == "Odd: quoting"
    assert current_etag("n.md") == snap.etag
    assert current_etag("missing.md") is None
    with pytest.raises(FileMissing):
        read("missing.md")


def test_package_reexports_everything_in_the_interface():
    for name in ("write", "write_new", "read", "current_etag", "resolve_safe", "WriteResult",
                 "NoteSnapshot", "WRITABLE_SUFFIXES", "Actor"):
        assert hasattr(vault_write, name), name
    assert os.path.basename(writer.__file__) == "writer.py"
