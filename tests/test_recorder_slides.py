"""Slide key-frame attachment (native macOS backend output → vault note)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import frontmatter
import pytest

from ghostbrain.recorder import slides
from ghostbrain.recorder.audio.darwin_native import frames_dir_for


@pytest.fixture
def tmp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    (vault / "20-contexts" / "work" / "calendar" / "transcripts").mkdir(parents=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    return vault


def _seed_frames(wav: Path, entries: list[dict], *, summary: bool = True) -> Path:
    frames = frames_dir_for(wav)
    frames.mkdir(parents=True, exist_ok=True)
    for e in entries:
        if e["image"] != "missing.jpg":
            (frames / e["image"]).write_bytes(b"\xff\xd8fake-jpeg")
    if summary:
        (frames / "slides.json").write_text(json.dumps({"version": 1, "slides": entries}))
    else:
        (frames / "slides.jsonl").write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return frames


def _note(vault: Path) -> Path:
    p = vault / "20-contexts" / "work" / "calendar" / "transcripts" / "standup-abcd1234.md"
    p.write_text("---\ntitle: Transcript\ntype: artifact\n---\n\n# Transcript\n\nhello world\n")
    return p


ENTRIES = [
    {"index": 1, "offset_ms": 4200, "image": "slide-0001-00004200.jpg",
     "text": "Q3 Roadmap\nShip recorder v2\nHire two engineers\nLaunch in September"},
    {"index": 2, "offset_ms": 65000, "image": "slide-0002-00065000.jpg", "text": "Thanks"},
    {"index": 3, "offset_ms": 90000, "image": "missing.jpg", "text": "this image does not exist on disk"},
]


def test_load_slides_from_json_and_jsonl(tmp_path: Path):
    wav = tmp_path / "a.wav"
    _seed_frames(wav, ENTRIES[:2])
    got = slides.load_slides(frames_dir_for(wav))
    assert [s.offset_s for s in got] == [4.2, 65.0]
    assert got[0].timestamp == "00:00:04"

    wav2 = tmp_path / "b.wav"
    _seed_frames(wav2, ENTRIES[:2], summary=False)
    assert len(slides.load_slides(frames_dir_for(wav2))) == 2


def test_load_slides_tolerates_missing_and_garbage(tmp_path: Path):
    assert slides.load_slides(tmp_path / "nope.frames") == []
    frames = tmp_path / "x.frames"
    frames.mkdir()
    (frames / "slides.json").write_text("{not json")
    assert slides.load_slides(frames) == []


def test_filter_slides_min_words(tmp_path: Path):
    wav = tmp_path / "a.wav"
    _seed_frames(wav, ENTRIES[:2])
    got = slides.filter_slides(slides.load_slides(frames_dir_for(wav)), min_words=3)
    assert [s.image.name for s in got] == ["slide-0001-00004200.jpg"]


def test_attach_slides_copies_assets_and_appends_section(tmp_vault: Path, tmp_path: Path):
    wav = tmp_path / "meeting-1.wav"
    _seed_frames(wav, ENTRIES)
    note = _note(tmp_vault)

    n = slides.attach_slides(note, wav, min_words=3)
    assert n == 1

    post = frontmatter.load(note)
    assert post.metadata["slideCount"] == 1
    asset_rel = post.metadata["slidesAssetDir"]
    assert asset_rel.startswith("90-meta/assets/transcripts/")
    assert asset_rel.endswith("/standup-abcd1234")
    assert (tmp_vault / asset_rel / "slide-0001-00004200.jpg").exists()

    body = post.content
    assert "## Slides" in body
    assert "**[00:00:04]**" in body
    assert f"![slide 00:00:04]({asset_rel}/slide-0001-00004200.jpg)" in body
    assert "> Q3 Roadmap" in body
    assert "[[00:00:04]]" not in body  # never wikilinks for timestamps
    assert not frames_dir_for(wav).exists()


def test_attach_slides_is_idempotent(tmp_vault: Path, tmp_path: Path):
    wav = tmp_path / "meeting-1.wav"
    _seed_frames(wav, ENTRIES[:1])
    note = _note(tmp_vault)
    assert slides.attach_slides(note, wav, min_words=1) == 1
    _seed_frames(wav, ENTRIES[:1])
    assert slides.attach_slides(note, wav, min_words=1) == 0
    assert frontmatter.load(note).content.count("## Slides") == 1
    assert not frames_dir_for(wav).exists()


def test_attach_slides_noop_without_frames(tmp_vault: Path, tmp_path: Path):
    note = _note(tmp_vault)
    before = note.read_text()
    assert slides.attach_slides(note, tmp_path / "blackhole.wav", min_words=8) == 0
    assert note.read_text() == before


def test_attach_slides_all_filtered_cleans_up(tmp_vault: Path, tmp_path: Path):
    wav = tmp_path / "meeting-1.wav"
    _seed_frames(wav, ENTRIES[1:2])
    note = _note(tmp_vault)
    assert slides.attach_slides(note, wav, min_words=8) == 0
    assert "## Slides" not in note.read_text()
    assert not frames_dir_for(wav).exists()


def test_sweep_orphan_frames(tmp_path: Path):
    rec = tmp_path / "recordings"
    rec.mkdir()
    old = rec / "gone.frames"
    old.mkdir()
    stale = time.time() - 2 * 24 * 3600
    os.utime(old, (stale, stale))
    fresh = rec / "fresh.frames"
    fresh.mkdir()
    live = rec / "live.frames"
    live.mkdir()
    os.utime(live, (stale, stale))
    (rec / "live.wav").write_bytes(b"x")

    assert slides.sweep_orphan_frames(rec) == 1
    assert not old.exists() and fresh.exists() and live.exists()
