"""Attach slide key-frames captured by the native helper to a transcript note.

The helper writes ``<wav>.frames/slides.json`` (plus an append-only
``slides.jsonl`` safety net) with one entry per deduplicated screen frame and
its OCR text. After the transcript note exists we:

1. copy the frame images into ``90-meta/assets/transcripts/<YYYY>/<MM>/<note-stem>/``
   (the one location both Obsidian and the desktop ``gbasset://`` resolver
   render, and one that is never indexed as notes),
2. append a ``## Slides`` section with timestamped OCR text + image embeds,
3. stamp ``slideCount`` / ``slidesAssetDir`` into the frontmatter,
4. delete the frames dir.

Everything here is best-effort and platform-neutral: on the BlackHole or
WASAPI backends there is no frames dir and every call is a cheap no-op.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter

from ghostbrain.paths import vault_path
from ghostbrain.recorder.audio.darwin_native import cleanup_control, frames_dir_for

log = logging.getLogger("ghostbrain.recorder.slides")

ASSET_ROOT = ("90-meta", "assets", "transcripts")
SECTION_HEADER = "## Slides"
MAX_QUOTE_LINES = 12
FRAMES_ORPHAN_AGE_S = 24 * 3600


@dataclasses.dataclass
class Slide:
    offset_s: float
    image: Path
    text: str

    @property
    def timestamp(self) -> str:
        total = max(0, int(self.offset_s))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"


def _entries_from_json(frames_dir: Path) -> list[dict[str, Any]]:
    summary = frames_dir / "slides.json"
    if summary.exists():
        try:
            data = json.loads(summary.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning("slides.json unreadable in %s: %s", frames_dir, e)
        else:
            if isinstance(data, dict) and isinstance(data.get("slides"), list):
                return [e for e in data["slides"] if isinstance(e, dict)]
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict)]
    jsonl = frames_dir / "slides.jsonl"
    entries: list[dict[str, Any]] = []
    if jsonl.exists():
        try:
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    entries.append(obj)
        except OSError as e:
            log.warning("slides.jsonl unreadable in %s: %s", frames_dir, e)
    return entries


def load_slides(frames_dir: Path) -> list[Slide]:
    """Parse the helper's output. Missing/malformed → ``[]``."""
    if not frames_dir.is_dir():
        return []
    slides: list[Slide] = []
    for entry in _entries_from_json(frames_dir):
        image_name = entry.get("image")
        if not isinstance(image_name, str) or not image_name:
            continue
        image = frames_dir / Path(image_name).name
        if not image.is_file():
            continue
        offset_ms = entry.get("offset_ms")
        if offset_ms is None:
            offset_ms = float(entry.get("offset_s") or 0.0) * 1000.0
        try:
            offset_s = float(offset_ms) / 1000.0
        except (TypeError, ValueError):
            offset_s = 0.0
        text = entry.get("text")
        slides.append(Slide(offset_s=offset_s, image=image,
                            text=str(text) if isinstance(text, str) else ""))
    slides.sort(key=lambda s: s.offset_s)
    return slides


def filter_slides(slides: list[Slide], *, min_words: int) -> list[Slide]:
    if min_words <= 0:
        return list(slides)
    return [s for s in slides if len(s.text.split()) >= min_words]


def _asset_dir_for(note_path: Path, when: datetime) -> tuple[Path, str]:
    rel = Path(*ASSET_ROOT) / f"{when.year:04d}" / f"{when.month:02d}" / note_path.stem
    return vault_path() / rel, rel.as_posix()


def _render_section(slides: list[Slide], asset_rel: str) -> str:
    lines = ["", SECTION_HEADER, ""]
    for s in slides:
        lines.append(f"**[{s.timestamp}]**")
        lines.append(f"![slide {s.timestamp}]({asset_rel}/{s.image.name})")
        quote = [ln.strip() for ln in s.text.splitlines() if ln.strip()][:MAX_QUOTE_LINES]
        for q in quote:
            lines.append(f"> {q}")
        lines.append("")
    return "\n".join(lines)


def attach_slides(note_path: Path, wav_path: Path, *, min_words: int) -> int:
    """Copy frames into the vault and append a Slides section. Returns how
    many slides were attached (0 when there is nothing to do)."""
    frames_dir = frames_dir_for(wav_path)
    if not frames_dir.is_dir():
        return 0
    if not note_path.is_file():
        log.warning("transcript note %s missing; leaving frames in place", note_path)
        return 0

    slides = filter_slides(load_slides(frames_dir), min_words=min_words)
    if not slides:
        log.info("no slides worth keeping for %s", wav_path.name)
        cleanup_frames(wav_path)
        return 0

    try:
        note = frontmatter.load(note_path)
    except Exception as e:  # noqa: BLE001
        log.warning("could not load %s: %s", note_path, e)
        return 0
    if re.search(rf"^{re.escape(SECTION_HEADER)}\s*$", note.content, flags=re.M):
        log.info("slides already attached to %s", note_path.name)
        cleanup_frames(wav_path)
        return 0

    asset_dir, asset_rel = _asset_dir_for(note_path, datetime.now(timezone.utc))
    asset_dir.mkdir(parents=True, exist_ok=True)
    kept: list[Slide] = []
    for s in slides:
        try:
            shutil.copy2(s.image, asset_dir / s.image.name)
        except OSError as e:
            log.warning("could not copy slide %s: %s", s.image.name, e)
            continue
        kept.append(s)
    if not kept:
        return 0

    note.content = note.content.rstrip("\n") + "\n" + _render_section(kept, asset_rel)
    note.metadata["slideCount"] = len(kept)
    note.metadata["slidesAssetDir"] = asset_rel
    note_path.write_text(frontmatter.dumps(note), encoding="utf-8")
    log.info("attached %d slide(s) to %s", len(kept), note_path.name)
    cleanup_frames(wav_path)
    return len(kept)


def cleanup_frames(wav_path: Path) -> None:
    shutil.rmtree(frames_dir_for(wav_path), ignore_errors=True)
    cleanup_control(wav_path)


def sweep_orphan_frames(recordings_dir: Path, *, now: float | None = None) -> int:
    """Remove ``*.frames`` dirs whose WAV is gone and that are older than a day
    (crash leftovers). Returns the number of directories removed."""
    if not recordings_dir.is_dir():
        return 0
    import time
    now = time.time() if now is None else now
    removed = 0
    for frames in recordings_dir.glob("*.frames"):
        if not frames.is_dir():
            continue
        wav = frames.with_suffix(".wav")
        if wav.exists():
            continue
        try:
            age = now - frames.stat().st_mtime
        except OSError:
            continue
        if age < FRAMES_ORPHAN_AGE_S:
            continue
        shutil.rmtree(frames, ignore_errors=True)
        removed += 1
    return removed
