"""One vault note per Drive file. New files go through the normal worker
pipeline (routing); changed files are rewritten in place, keeping all
frontmatter the pipeline or the user set. The filename suffix ``-<fileId>.md``
is the lookup key, so there is no separate index."""
from __future__ import annotations

import logging
import os
import stat
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ghostbrain.connectors.gdrive.drive import parse_time
from ghostbrain.paths import vault_path
from ghostbrain.worker import note_generator, pipeline

log = logging.getLogger("ghostbrain.connectors.gdrive.store")

# Sync and backfill both run in the sidecar's scheduler threads; one lock
# makes "look up, then import or rewrite" atomic across them.
_lock = threading.Lock()


def find_notes(file_id: str) -> list[Path]:
    root = vault_path()
    pattern = f"*-{file_id}.md"
    found = sorted((root / "00-inbox" / "raw" / "gdrive").glob(pattern))
    contexts = root / "20-contexts"
    if contexts.exists():
        found += sorted(contexts.glob(f"*/gdrive/**/{pattern}"))
    return found


def _split(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    return yaml.safe_load(text[4:end]) or {}, text[end + 5:]


def _as_time(value) -> datetime | None:
    """The stored ``driveModifiedTime`` as an aware datetime. Naive values
    (e.g. set through a date picker) count as UTC; anything unparseable is
    None, which forces a rewrite."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            return parse_time(value)
        except ValueError:
            return None
    return None


def _stored_time(path: Path) -> datetime | None:
    return _as_time(_split(path.read_text(encoding="utf-8"))[0].get("driveModifiedTime"))


def _is_current_note(path: Path, modified: datetime) -> bool:
    stored = _stored_time(path)
    return stored is not None and stored >= modified


def is_current(file_id: str, modified_time: str) -> bool:
    """True when the file already has notes and every copy holds this
    ``modifiedTime`` or newer — the caller can skip downloading it."""
    paths = find_notes(file_id)
    modified = parse_time(modified_time)
    return bool(paths) and all(_is_current_note(p, modified) for p in paths)


def _write_atomic(path: Path, text: str) -> None:
    """Temp file in the same directory, then ``os.replace`` — a crash never
    leaves a half-written note. Keeps the note's existing permissions."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            os.chmod(tmp, stat.S_IMODE(path.stat().st_mode))
        except FileNotFoundError:
            pass
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _rewrite(path: Path, event: dict) -> None:
    front, _ = _split(path.read_text(encoding="utf-8"))
    md = event["metadata"]
    front["title"] = event["title"]
    front["updated"] = event["timestamp"]
    front["driveModifiedTime"] = md["driveModifiedTime"]
    front["truncated"] = md["truncated"]
    if md.get("folder"):
        front["folder"] = md["folder"]
    _write_atomic(path, note_generator._render(front, event["body"]))


def upsert(event: dict) -> tuple[str, dict | None]:
    """(outcome, pipeline result). The result is only set for 'imported' —
    callers use it to spot LLM-routing fallbacks."""
    md = event["metadata"]
    with _lock:
        paths = find_notes(md["fileId"])
        if not paths:
            return "imported", pipeline.process_event(event)
        modified = parse_time(md["driveModifiedTime"])
        # Every copy is checked, so one left stale by an interrupted
        # rewrite heals on the next pass.
        stale = [p for p in paths if not _is_current_note(p, modified)]
        if not stale:
            return "skipped", None
        for p in stale:
            _rewrite(p, event)
        return "updated", None
