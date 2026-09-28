"""One vault note per Drive file. New files go through the normal worker
pipeline (routing); changed files are rewritten in place, keeping all
frontmatter the pipeline or the user set. The filename suffix ``-<fileId>.md``
is the lookup key, so there is no separate index."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
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
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        return parse_time(value)
    return None


def _rewrite(path: Path, event: dict) -> None:
    front, _ = _split(path.read_text(encoding="utf-8"))
    md = event["metadata"]
    front["title"] = event["title"]
    front["updated"] = event["timestamp"]
    front["driveModifiedTime"] = md["driveModifiedTime"]
    front["truncated"] = md["truncated"]
    if md.get("folder"):
        front["folder"] = md["folder"]
    path.write_text(note_generator._render(front, event["body"]), encoding="utf-8")


def upsert(event: dict) -> tuple[str, dict | None]:
    """(outcome, pipeline result). The result is only set for 'imported' —
    callers use it to spot LLM-routing fallbacks."""
    md = event["metadata"]
    with _lock:
        paths = find_notes(md["fileId"])
        if not paths:
            return "imported", pipeline.process_event(event)
        stored = _as_time(_split(paths[0].read_text(encoding="utf-8"))[0].get("driveModifiedTime"))
        if stored is not None and stored >= parse_time(md["driveModifiedTime"]):
            return "skipped", None
        for p in paths:
            _rewrite(p, event)
        return "updated", None
