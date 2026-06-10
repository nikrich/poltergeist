"""Recent activity, per-day listing, and heatmap aggregation from the audit log."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from ghostbrain.paths import audit_dir

log = logging.getLogger("ghostbrain.api.repo.activity")


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
    """Bucket an audit event by source.

    `digest_generated` → "digest"; an explicit `source` field wins; everything
    else (scheduler/connector internals with no source) buckets as "system".
    Shared by the activity rows AND the heatmap aggregation so the activity
    screen's source chips line up with the day-log rows.
    """
    et = event.get("event_type", "")
    if et == "digest_generated":
        return "digest"
    src = event.get("source")
    return src if isinstance(src, str) and src else "system"


def _iter_day_events(path: Path) -> Iterator[tuple[int, dict]]:
    """Yield (lineno, event) for each well-formed line of one audit file.

    Malformed lines are skipped with a warning — a corrupt line must never
    500 an endpoint.
    """
    for lineno, line in enumerate(path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log.warning("skipping malformed audit line %s:%d", path.name, lineno)
            continue
        if not isinstance(event, dict):
            log.warning("skipping non-object audit line %s:%d", path.name, lineno)
            continue
        yield lineno, event


def _row_for(event: dict, *, row_id: str) -> dict | None:
    """Build one ActivityRow dict, or None when the ts is unusable.

    The returned dict carries a private "_when" datetime for callers that
    need to filter by time; callers must pop it before returning rows.
    """
    ts_str = event.get("ts", "")
    try:
        when = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return {
        "id": row_id,
        "source": _source_for(event),
        "verb": _verb_for(event.get("event_type", "")),
        "subject": _subject_for(event),
        "atRelative": _relative(when),
        "at": ts_str,
        "path": _note_path_for(event),
        "_when": when,
    }


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
        for lineno, event in _iter_day_events(path):
            event_id = event.get("event_id")
            row_id = str(event_id) if event_id else f"audit-{day.isoformat()}-{lineno}"
            row = _row_for(event, row_id=row_id)
            if row is None:
                continue
            when = row.pop("_when")
            if when < cutoff:
                continue
            items.append(row)
    items.sort(key=lambda r: r["at"], reverse=True)
    return items


def list_activity_for_date(day: date) -> list[dict]:
    """All audit rows for one calendar day, newest first.

    Row ids are always synthesized from the line number: real audit logs
    repeat event_id within a day (e.g. connector_skipped/joplin on every
    scheduler cycle) and the renderer keys rows by id.
    """
    path = audit_dir() / f"{day.isoformat()}.jsonl"
    if not path.exists():
        return []
    items: list[dict] = []
    for lineno, event in _iter_day_events(path):
        row = _row_for(event, row_id=f"audit-{day.isoformat()}-{lineno}")
        if row is None:
            continue
        row.pop("_when")
        items.append(row)
    items.sort(key=lambda r: r["at"], reverse=True)
    return items


def build_heatmap(days: int = 365) -> dict:
    """Aggregate per-day event counts + per-source breakdown.

    Walks the audit directory once. Days with no audit file — or whose file
    yields zero well-formed events — are omitted; the renderer fills
    zero-level squares. maxCount lets the renderer bucket intensities
    without a second pass.
    """
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    audit = audit_dir()
    if not audit.exists():
        return {"days": [], "total": 0, "maxCount": 0}
    out: list[dict] = []
    total = 0
    max_count = 0
    for path in sorted(audit.glob("*.jsonl")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            log.warning("ignoring non-date audit file %s", path.name)
            continue
        if day < start or day > today:
            continue
        count = 0
        by_source: dict[str, int] = {}
        for _lineno, event in _iter_day_events(path):
            count += 1
            src = _source_for(event)
            by_source[src] = by_source.get(src, 0) + 1
        if count == 0:
            continue
        out.append({"date": day.isoformat(), "count": count, "bySource": by_source})
        total += count
        max_count = max(max_count, count)
    return {"days": out, "total": total, "maxCount": max_count}
