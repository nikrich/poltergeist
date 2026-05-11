"""Recent activity from audit log."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ghostbrain.paths import audit_dir


def _relative(when: datetime) -> str:
    delta = datetime.now(timezone.utc) - when
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86_400:
        return f"{secs // 3600}h"
    return f"{secs // 86_400}d"


def _verb_for(event_type: str) -> str:
    mapping = {
        "digest_generated": "wrote digest",
        "event_processed": "processed",
        "event_routed": "routed",
        "artifact_extracted": "extracted",
    }
    if event_type in mapping:
        return mapping[event_type]
    return event_type.replace("_", " ")


def _strip_inbox_timestamp_prefix(name: str) -> str:
    """Strip leading 'YYYYMMDDTHHMMSS-' prefix from inbox basenames."""
    parts = name.split("-", 1)
    if len(parts) < 2:
        return name
    head = parts[0]
    # The inbox convention is e.g. '20260507T144500'. Check it looks like
    # 8-digit-date + 'T' + time.
    if "T" in head and head[:8].isdigit():
        return parts[1]
    return name


def _subject_for(event: dict) -> str:
    inbox_path = event.get("inbox_path")
    if isinstance(inbox_path, str) and inbox_path:
        return _strip_inbox_timestamp_prefix(Path(inbox_path).stem)
    path = event.get("path")
    if isinstance(path, str) and path:
        return Path(path).stem
    event_id = event.get("event_id")
    if event_id:
        return str(event_id)
    return ""


def _note_path_for(event: dict) -> str | None:
    """Vault-relative path of the note this audit row is about, if any.

    The audit log stores absolute paths or vault-relative paths depending on
    the producer. Strip a leading vault prefix when present so the UI can
    feed the result straight into /v1/notes?path=...
    """
    from ghostbrain.paths import vault_path

    raw = event.get("inbox_path") or event.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith("/"):
        try:
            return str(Path(raw).resolve().relative_to(vault_path().resolve()))
        except ValueError:
            return None
    return raw


def _source_for(event: dict) -> str:
    et = event.get("event_type", "")
    if et == "digest_generated":
        return "digest"
    src = event.get("source")
    return src if isinstance(src, str) and src else "ghostbrain"


def list_activity(window_minutes: int = 240) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    audit = audit_dir()
    if not audit.exists():
        return []
    items: list[dict] = []
    today = datetime.now(timezone.utc).date()
    for offset in range(2):  # today + yesterday (covers any reasonable windowMinutes)
        day = today - timedelta(days=offset)
        path = audit / f"{day.isoformat()}.jsonl"
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text().splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = event.get("ts", "")
            try:
                when = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            except (ValueError, TypeError, AttributeError):
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=timezone.utc)
            if when < cutoff:
                continue
            event_id = event.get("event_id")
            row_id = str(event_id) if event_id else f"audit-{day.isoformat()}-{lineno}"
            items.append({
                "id": row_id,
                "source": _source_for(event),
                "verb": _verb_for(event.get("event_type", "")),
                "subject": _subject_for(event),
                "atRelative": _relative(when),
                "at": ts_str,
                "path": _note_path_for(event),
            })
    items.sort(key=lambda r: r["at"], reverse=True)
    return items
