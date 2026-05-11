"""Orphan manual-recording recovery.

The calendar-driven pipeline in ``daemon.py`` covers events on the user's
calendar. A user-initiated recording (started by hand, outside any calendar
event) doesn't have a matching event to link against, so the existing flow
ignores it: ffmpeg writes the WAV, you stop it, and the audio just sits
there forever.

This module fills that gap. Each daemon tick (and on demand via the CLI):

1. Scan ``~/ghostbrain/recorder/recordings/*-manual.wav``.
2. For each WAV with no matching transcript and no live writer, transcribe
   with whisper-cli, derive a 4–8-word title via ``claude -p``, and file
   the transcript markdown under ``20-contexts/<ctx>/calendar/transcripts/``.
3. Mark the WAV processed so we don't re-handle it.

The destination context defaults to ``personal`` and is configurable via
``recorder.manual_context`` in ``<vault>/90-meta/config.yaml``.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import frontmatter
import yaml

from ghostbrain.llm.client import LLMError, run as llm_run
from ghostbrain.paths import vault_path
from ghostbrain.recorder.audio_capture import is_running
from ghostbrain.recorder.transcribe import TranscribeError, transcribe

log = logging.getLogger("ghostbrain.recorder.manual")

DEFAULT_RECORDINGS_DIR = Path.home() / "ghostbrain" / "recorder" / "recordings"
DEFAULT_MANUAL_CONTEXT = "personal"
MIN_AGE_SECONDS = 60  # wait at least this long after last mtime before assuming a wav is "done"
MIN_SIZE_BYTES = 100_000
PROCESSED_MARKER_KEY = "manualRecordingId"  # stamp into the transcript frontmatter


@dataclass
class ManualConfig:
    enabled: bool
    context: str
    recordings_dir: Path


def load_config() -> ManualConfig:
    cfg_file = vault_path() / "90-meta" / "config.yaml"
    cfg: dict = {}
    if cfg_file.exists():
        cfg = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    rec = cfg.get("recorder") or {}
    return ManualConfig(
        enabled=bool(rec.get("manual_enabled", True)),
        context=str(rec.get("manual_context") or DEFAULT_MANUAL_CONTEXT),
        recordings_dir=Path(rec.get("recordings_dir") or DEFAULT_RECORDINGS_DIR),
    )


def _looks_alive(wav: Path, *, now: float) -> bool:
    """Is ffmpeg likely still writing to this file?"""
    try:
        mtime = wav.stat().st_mtime
    except OSError:
        return False
    return (now - mtime) < MIN_AGE_SECONDS


def _stale_pid_from_state(state_file: Path) -> int | None:
    """Read PID from `manual.state` if it exists, else None."""
    if not state_file.exists():
        return None
    try:
        first = state_file.read_text(encoding="utf-8").splitlines()[0]
        return int(first.strip())
    except (OSError, IndexError, ValueError):
        return None


def _already_filed(wav_id: str) -> bool:
    """A transcript stamped with this wav's id already exists anywhere in the vault?

    Scans every ``20-contexts/*/calendar/transcripts/`` directory so a recording
    filed manually under one context isn't re-transcribed when the configured
    ``manual_context`` is a different one.
    """
    root = vault_path()
    if not root.exists():
        return False
    for note in root.glob("20-contexts/*/calendar/transcripts/*.md"):
        try:
            fm = frontmatter.load(note).metadata
        except Exception:  # noqa: BLE001
            continue
        if fm.get(PROCESSED_MARKER_KEY) == wav_id:
            return True
    return False


_TITLE_PROMPT = (
    "Title this working meeting in 4-8 words. The title should reference "
    "the most concrete topic discussed (project name, feature, decision), "
    "not generic terms like 'feature work' or 'coordination'. Output ONLY "
    "the title, no quotes, no period.\n\nTranscript:\n---\n{}\n---"
)


def _derive_title(transcript_text: str) -> str:
    sample = transcript_text[:15000]
    try:
        result = llm_run(_TITLE_PROMPT.format(sample), model="sonnet")
        title = result.text.strip().strip('"').strip("'").rstrip(".")
        if title:
            return title
    except LLMError as e:
        log.warning("title LLM failed: %s; using fallback", e)
    return "Manual recording"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or "manual-recording"


def _duration_seconds(wav: Path, fallback_started: datetime) -> float:
    """Best-effort: mtime - mtime-of-creation. Falls back to mtime-of-now."""
    try:
        stats = wav.stat()
    except OSError:
        return 0.0
    finished = datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc)
    return max(0.0, (finished - fallback_started).total_seconds())


def _parse_started_from_name(wav: Path) -> datetime:
    """Recordings are named meeting-YYYYMMDD-HHMMSS-manual.wav (local TZ)."""
    match = re.search(r"-(\d{8})-(\d{6})-", wav.name)
    if not match:
        return datetime.fromtimestamp(wav.stat().st_mtime, tz=timezone.utc)
    date_part, time_part = match.group(1), match.group(2)
    try:
        local = datetime.strptime(date_part + time_part, "%Y%m%d%H%M%S")
    except ValueError:
        return datetime.fromtimestamp(wav.stat().st_mtime, tz=timezone.utc)
    return local.astimezone(timezone.utc)


def _file_transcript(
    *,
    wav: Path,
    transcript_text: str,
    title: str,
    context: str,
    started: datetime,
    duration_s: float,
) -> Path:
    transcripts_dir = vault_path() / "20-contexts" / context / "calendar" / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    short = uuid.uuid4().hex[:8]
    filename = f"{_slugify(title)}-{short}.md"
    target = transcripts_dir / filename

    fm = {
        "artifactType": "transcript",
        "context": context,
        "created": datetime.now(timezone.utc).isoformat(),
        "durationSeconds": round(duration_s, 1),
        "id": str(uuid.uuid4()),
        "source": "recorder",
        "started": started.isoformat(),
        "title": f"Transcript: {title}",
        "type": "artifact",
        PROCESSED_MARKER_KEY: wav.name,
    }

    started_local = started.astimezone()
    body = (
        f"# Transcript — {title}\n\n"
        f"_Started: {started_local.strftime('%Y-%m-%d %H:%M %Z')}_\n\n"
        f"{transcript_text.strip()}\n"
    )

    post = frontmatter.Post(body, **fm)
    target.write_text(frontmatter.dumps(post), encoding="utf-8")
    return target


def recover_one(
    wav: Path,
    config: ManualConfig,
    *,
    title_override: str | None = None,
    started_override: "datetime | None" = None,
) -> Path | None:
    """Recover a single orphan WAV. Returns the transcript path or None.

    `title_override` skips the LLM-title step (useful when the user provided
    a title up front). `started_override` skips the filename-based start-time
    derivation (useful when the manual flow knows the exact start instant).
    """
    if _already_filed(wav.name):
        return None

    log.info("recovering orphan manual recording: %s", wav.name)
    started = started_override or _parse_started_from_name(wav)

    try:
        txt_path = transcribe(wav)
    except TranscribeError as e:
        log.warning("transcribe failed for %s: %s", wav.name, e)
        return None

    transcript_text = txt_path.read_text(encoding="utf-8")
    if not transcript_text.strip():
        log.warning("empty transcript for %s; skipping", wav.name)
        return None

    title = title_override or _derive_title(transcript_text)
    duration_s = _duration_seconds(wav, started)

    return _file_transcript(
        wav=wav,
        transcript_text=transcript_text,
        title=title,
        context=config.context,
        started=started,
        duration_s=duration_s,
    )


def run_recovery_pass(config: ManualConfig | None = None) -> list[Path]:
    """Recover every orphan manual recording. Returns the new transcript paths."""
    cfg = config or load_config()
    if not cfg.enabled:
        return []

    if not cfg.recordings_dir.exists():
        return []

    now = time.time()
    state_pid = _stale_pid_from_state(cfg.recordings_dir.parent / "manual.state")
    if state_pid is not None and is_running(state_pid):
        # Real active recording — leave the directory alone.
        return []

    recovered: list[Path] = []
    for wav in sorted(cfg.recordings_dir.glob("*-manual.wav")):
        if wav.stat().st_size < MIN_SIZE_BYTES:
            continue
        if _looks_alive(wav, now=now):
            continue
        try:
            result = recover_one(wav, cfg)
        except Exception:  # noqa: BLE001
            log.exception("recovery failed for %s", wav.name)
            continue
        if result is not None:
            recovered.append(result)

    # If we successfully recovered anything, sweep the stale state file.
    if recovered:
        state_file = cfg.recordings_dir.parent / "manual.state"
        if state_file.exists() and state_pid is None:
            try:
                state_file.unlink()
            except OSError:
                pass

    return recovered
