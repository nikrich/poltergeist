"""LinkIndex: incremental refresh, resolution, backlinks, ghosts, cold build."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import ghostbrain.vault_index.links as links_mod
from ghostbrain.vault_index.links import Edge, LinkIndex, get_link_index, warm_link_index


def _write(root: Path, rel: str, text: str, *, mtime_ns: int | None = None) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if mtime_ns is not None:
        os.utime(p, ns=(mtime_ns, mtime_ns))
    return p


def _idx(root: Path) -> LinkIndex:
    return LinkIndex(root, refresh_interval=0)


def test_build_indexes_only_configured_roots(tmp_path: Path):
    for rel in (
        "20-contexts/work/a.md",
        "30-cross-context/people/alex.md",
        "00-inbox/raw/manual/j.md",
        "10-daily/2026-10-09.md",
        "00-inbox/raw/gmail/g.md",
        "90-meta/x.md",
        "20-contexts/work/.hidden/h.md",
        "20-contexts/work/readme.txt",
    ):
        _write(tmp_path, rel, "x")
    idx = _idx(tmp_path)
    assert idx.ready is False
    idx.refresh()
    assert idx.ready is True
    assert idx.generation == 1
    assert {e.path for e in idx.entries()} == {
        "20-contexts/work/a.md",
        "30-cross-context/people/alex.md",
        "00-inbox/raw/manual/j.md",
        "10-daily/2026-10-09.md",
    }


def test_refresh_reparses_only_changed_files(tmp_path: Path, monkeypatch):
    calls: list[str] = []
    real = links_mod.parse_note

    def counting(rel, text, **kw):
        calls.append(rel)
        return real(rel, text, **kw)

    monkeypatch.setattr(links_mod, "parse_note", counting)
    _write(tmp_path, "20-contexts/work/a.md", "---\ntitle: A\n---\n", mtime_ns=1_000_000_000)
    _write(tmp_path, "20-contexts/work/b.md", "b", mtime_ns=1_000_000_000)
    idx = _idx(tmp_path)
    idx.refresh()
    assert sorted(calls) == ["20-contexts/work/a.md", "20-contexts/work/b.md"]
    gen = idx.generation

    idx.refresh()
    assert len(calls) == 2  # nothing changed, nothing re-parsed
    assert idx.generation == gen

    _write(tmp_path, "20-contexts/work/a.md", "---\ntitle: A2\n---\n", mtime_ns=2_000_000_000)
    idx.refresh()
    assert calls[2:] == ["20-contexts/work/a.md"]
    assert idx.get("20-contexts/work/a.md").title == "A2"
    assert idx.generation == gen + 1


def test_same_mtime_different_size_is_detected(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/a.md", "---\ntitle: A\n---\n", mtime_ns=5_000_000_000)
    idx = _idx(tmp_path)
    idx.refresh()
    _write(tmp_path, "20-contexts/work/a.md", "---\ntitle: Longer\n---\n", mtime_ns=5_000_000_000)
    idx.refresh()
    assert idx.get("20-contexts/work/a.md").title == "Longer"


def test_removed_file_drops_entry_and_backlinks(tmp_path: Path):
    a = _write(tmp_path, "20-contexts/work/a.md", "see [[20-contexts/work/b]]")
    _write(tmp_path, "20-contexts/work/b.md", "b")
    idx = _idx(tmp_path)
    idx.refresh()
    assert [e.source for e in idx.backlinks("20-contexts/work/b.md")] == ["20-contexts/work/a.md"]
    a.unlink()
    idx.refresh()
    assert idx.get("20-contexts/work/a.md") is None
    assert idx.backlinks("20-contexts/work/b.md") == []


def test_backlinks_and_outgoing_carry_snippets(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/a.md", "line one\nsee [[20-contexts/work/b|B]] here\n")
    _write(tmp_path, "20-contexts/work/b.md", "self [[20-contexts/work/b]]")
    idx = _idx(tmp_path)
    idx.refresh()
    expected = Edge(
        source="20-contexts/work/a.md",
        target="20-contexts/work/b.md",
        exists=True,
        kind="wikilink",
        weight=0.5,
        snippet="see [[20-contexts/work/b|B]] here",
    )
    assert idx.backlinks("20-contexts/work/b.md") == [expected]  # self-link excluded
    assert idx.outgoing("20-contexts/work/a.md") == [expected]
    assert idx.outgoing("20-contexts/work/missing.md") == []


def test_bare_name_links_resolve_when_unique(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/Beta.md", "b")
    _write(tmp_path, "20-contexts/work/a.md", "see [[beta]]")
    idx = _idx(tmp_path)
    idx.refresh()
    assert idx.resolve("beta.md") == "20-contexts/work/Beta.md"
    assert [e.source for e in idx.backlinks("20-contexts/work/Beta.md")] == ["20-contexts/work/a.md"]

    _write(tmp_path, "20-contexts/side-project/beta.md", "another")
    idx.refresh()
    assert idx.resolve("beta.md") == "beta.md"  # ambiguous: left unresolved
    assert idx.backlinks("20-contexts/work/Beta.md") == []


def test_ghosts_report_unwritten_targets(tmp_path: Path):
    _write(
        tmp_path,
        "20-contexts/work/a.md",
        "[[20-contexts/work/missing]] [[20-contexts/work/b]] [[90-meta/routing]]",
    )
    _write(tmp_path, "20-contexts/work/c.md", "[[20-contexts/work/missing|M]]")
    _write(tmp_path, "20-contexts/work/b.md", "b")
    _write(tmp_path, "90-meta/routing.md", "outside the indexed roots, but real")
    idx = _idx(tmp_path)
    idx.refresh()
    assert idx.ghosts() == {"20-contexts/work/missing.md": 2}
    flags = {e.target: e.exists for e in idx.outgoing("20-contexts/work/a.md")}
    assert flags == {
        "20-contexts/work/missing.md": False,
        "20-contexts/work/b.md": True,
        "90-meta/routing.md": True,
    }
    assert idx.exists("../outside.md") is False
    assert idx.exists("C:/x.md") is False  # drive letter: would escape the vault on Windows
    assert idx.exists("a/b:c.md") is False


def test_malformed_and_binary_files_do_not_abort_build(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/bad.md", "---\ntitle: [unclosed\n---\n[[20-contexts/work/ok]]")
    p = tmp_path / "20-contexts/work/bin.md"
    p.write_bytes(b"\xff\xfe\x00 not utf8 [[20-contexts/work/ok]]")
    _write(tmp_path, "20-contexts/work/ok.md", "---\ntitle: OK\n---\n")
    idx = _idx(tmp_path)
    idx.refresh()
    assert idx.get("20-contexts/work/bad.md").title == "bad"
    assert idx.get("20-contexts/work/bin.md").title == "bin"
    assert idx.get("20-contexts/work/ok.md").title == "OK"
    assert len(idx.backlinks("20-contexts/work/ok.md")) == 2


def test_ensure_fresh_throttles_incremental_refresh(tmp_path: Path):
    now = [100.0]
    _write(tmp_path, "20-contexts/work/a.md", "a")
    idx = LinkIndex(tmp_path, refresh_interval=2.0, clock=lambda: now[0])
    assert idx.ensure_fresh(wait=5.0) is True  # cold build finishes within wait
    _write(tmp_path, "20-contexts/work/b.md", "b")
    now[0] = 101.0
    assert idx.ensure_fresh() is True
    assert idx.get("20-contexts/work/b.md") is None  # throttled
    now[0] = 102.5
    assert idx.ensure_fresh() is True  # returns at once; refresh runs in the background
    assert idx._join_refresh(5.0) is True
    assert idx.get("20-contexts/work/b.md") is not None


def test_ensure_fresh_does_not_block_on_a_slow_refresh(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/a.md", "a")
    idx = _idx(tmp_path)
    idx.refresh()
    _write(tmp_path, "20-contexts/work/b.md", "b")
    gate = threading.Event()
    scans: list[int] = []
    real_scan = idx._scan

    def slow_scan():
        scans.append(1)
        gate.wait(5)
        return real_scan()

    idx._scan = slow_scan  # type: ignore[method-assign]
    assert idx.ensure_fresh() is True
    # Had ensure_fresh refreshed synchronously it would have waited out the
    # gate and already indexed b.md.
    assert idx.get("20-contexts/work/b.md") is None
    assert idx.ensure_fresh() is True
    assert idx.get("20-contexts/work/a.md") is not None  # current data still served
    gate.set()
    assert idx._join_refresh(5.0) is True
    assert len(scans) == 1  # single-flight: the second call started nothing
    assert idx.get("20-contexts/work/b.md") is not None


def test_ensure_fresh_returns_false_while_cold_build_runs(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/a.md", "a")
    idx = _idx(tmp_path)
    gate = threading.Event()
    scans: list[int] = []
    real_scan = idx._scan

    def slow_scan():
        scans.append(1)
        gate.wait(5)
        return real_scan()

    idx._scan = slow_scan  # type: ignore[method-assign]
    assert idx.ensure_fresh(wait=0) is False
    assert idx.ensure_fresh(wait=0.05) is False
    assert len(scans) == 1  # a second caller never starts a second build
    gate.set()
    assert idx.wait_until_ready(5.0) is True
    assert idx.ensure_fresh(wait=0) is True
    assert idx.get("20-contexts/work/a.md") is not None


def test_get_link_index_is_one_per_vault(tmp_path: Path, monkeypatch):
    a, b = tmp_path / "va", tmp_path / "vb"
    a.mkdir()
    b.mkdir()
    assert get_link_index(a) is get_link_index(a)
    assert get_link_index(a) is not get_link_index(b)
    monkeypatch.setenv("VAULT_PATH", str(a))
    assert get_link_index() is get_link_index(a)


def test_warm_link_index_never_raises(monkeypatch):
    def boom(root=None):
        raise RuntimeError("no vault")

    monkeypatch.setattr(links_mod, "get_link_index", boom)
    warm_link_index()  # must not raise


# ── note_changed: read-your-writes for the API's own saves ──────────────────
def _slow_idx(root: Path) -> LinkIndex:
    """Throttle so long that only note_changed can make a change visible."""
    return LinkIndex(root, refresh_interval=3600)


def test_note_changed_makes_a_new_backlink_visible_without_refresh(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/b.md", "b")
    a = _write(tmp_path, "20-contexts/work/a.md", "nothing yet")
    idx = _slow_idx(tmp_path)
    idx.refresh()
    gen = idx.generation
    a.write_text("now see [[20-contexts/work/b]]", encoding="utf-8")
    idx.note_changed("20-contexts/work/a.md")
    assert [e.source for e in idx.backlinks("20-contexts/work/b.md")] == ["20-contexts/work/a.md"]
    assert idx.generation == gen + 1
    idx.note_changed("20-contexts/work/a.md")  # unchanged: no bump
    assert idx.generation == gen + 1


def test_note_changed_indexes_a_new_file(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/b.md", "b")
    idx = _slow_idx(tmp_path)
    idx.refresh()
    _write(tmp_path, "00-inbox/raw/manual/j.md", "jot about [[20-contexts/work/b]]")
    idx.note_changed("00-inbox/raw/manual/j.md")
    assert [e.source for e in idx.backlinks("20-contexts/work/b.md")] == ["00-inbox/raw/manual/j.md"]


def test_note_changed_drops_a_deleted_file(tmp_path: Path):
    a = _write(tmp_path, "20-contexts/work/a.md", "see [[20-contexts/work/b]]")
    _write(tmp_path, "20-contexts/work/b.md", "b")
    idx = _slow_idx(tmp_path)
    idx.refresh()
    gen = idx.generation
    a.unlink()
    idx.note_changed("20-contexts/work/a.md")
    assert idx.get("20-contexts/work/a.md") is None
    assert idx.backlinks("20-contexts/work/b.md") == []
    assert idx.generation == gen + 1


def test_note_changed_ignores_unindexed_paths_and_cold_index(tmp_path: Path):
    _write(tmp_path, "90-meta/x.md", "see [[20-contexts/work/b]]")
    _write(tmp_path, "20-contexts/work/.hidden/h.md", "see [[20-contexts/work/b]]")
    _write(tmp_path, "20-contexts/work/a.md", "see [[20-contexts/work/b]]")
    idx = _slow_idx(tmp_path)
    idx.note_changed("20-contexts/work/a.md")  # not ready: the cold build will see it
    assert idx.entries() == []
    idx.refresh()
    gen = idx.generation
    for rel in ("90-meta/x.md", "20-contexts/work/.hidden/h.md", "../outside.md", "/abs.md",
                "C:/x.md", "20-contexts/work/readme.txt", ""):
        idx.note_changed(rel)
    assert idx.generation == gen
    assert {e.path for e in idx.entries()} == {"20-contexts/work/a.md"}


def test_note_changed_never_raises(tmp_path: Path, monkeypatch):
    _write(tmp_path, "20-contexts/work/a.md", "a")
    idx = _slow_idx(tmp_path)
    idx.refresh()
    monkeypatch.setattr(idx, "_read", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    _write(tmp_path, "20-contexts/work/a.md", "changed")
    idx.note_changed("20-contexts/work/a.md")  # logged, not raised


def test_in_flight_refresh_does_not_clobber_note_changed(tmp_path: Path):
    """A refresh that parsed an older version must not overwrite a newer note_changed."""
    from ghostbrain.vault_index.parse import parse_note

    a = _write(tmp_path, "20-contexts/work/a.md", "v1", mtime_ns=1_000_000_000)
    _write(tmp_path, "20-contexts/work/b.md", "b")
    idx = _slow_idx(tmp_path)
    idx.refresh()
    _write(tmp_path, "20-contexts/work/a.md", "v2 old", mtime_ns=2_000_000_000)
    real_read = idx._read
    raced = {"done": False}

    def racing_read(rel, sig):
        if rel == "20-contexts/work/a.md" and not raced["done"]:
            raced["done"] = True
            a.write_text("v3 see [[20-contexts/work/b]] now", encoding="utf-8")
            idx.note_changed(rel)  # the app's own save lands mid-refresh
            return parse_note(rel, "v2 old", mtime_ns=sig[0], size=sig[1])
        return real_read(rel, sig)

    idx._read = racing_read  # type: ignore[method-assign]
    idx.refresh()
    assert [e.source for e in idx.backlinks("20-contexts/work/b.md")] == ["20-contexts/work/a.md"]


def test_note_embed_is_a_backlink_but_attachment_embed_is_not(tmp_path: Path):
    _write(tmp_path, "20-contexts/work/b.md", "b")
    _write(tmp_path, "20-contexts/work/a.md", "![[20-contexts/work/b]]\n![[90-meta/assets/x.png]]")
    idx = _idx(tmp_path)
    idx.refresh()
    assert [(e.source, e.snippet) for e in idx.backlinks("20-contexts/work/b.md")] == [
        ("20-contexts/work/a.md", "![[20-contexts/work/b]]"),
    ]
    assert [e.target for e in idx.outgoing("20-contexts/work/a.md")] == ["20-contexts/work/b.md"]
