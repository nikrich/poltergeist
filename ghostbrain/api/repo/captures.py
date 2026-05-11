"""Capture aggregation from queue + audit."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ghostbrain.paths import audit_dir, queue_dir


def _is_recent(iso: str, hours: int = 6) -> bool:
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - when) < timedelta(hours=hours)


def _record_from_payload(capture_id: str, payload: dict) -> dict:
    captured_at = payload.get("capturedAt", "")
    return {
        "id": capture_id,
        "source": payload.get("source", "unknown"),
        "title": payload.get("title", "(no title)"),
        "snippet": payload.get("snippet", ""),
        "from": payload.get("from", ""),
        "tags": payload.get("tags", []),
        "unread": _is_recent(captured_at) if captured_at else False,
        "capturedAt": captured_at,
    }


def _list_pending() -> list[tuple[dict, dict]]:
    """Returns list of (record, full_payload) tuples."""
    pending = queue_dir() / "pending"
    if not pending.exists():
        return []
    out = []
    for p in pending.iterdir():
        if not p.is_file() or p.suffix != ".json":
            continue
        try:
            payload = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        out.append((_record_from_payload(p.stem, payload), payload))
    return out


def _list_audit(days_back: int = 2) -> list[tuple[dict, dict]]:
    audit = audit_dir()
    if not audit.exists():
        return []
    out = []
    today = datetime.now(timezone.utc).date()
    for offset in range(days_back + 1):
        day = today - timedelta(days=offset)
        path = audit / f"{day.isoformat()}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            capture_id = payload.get("id") or f"audit-{day}-{len(out)}"
            out.append((_record_from_payload(capture_id, payload), payload))
    return out


def list_captures(
    limit: int = 50, offset: int = 0, source: str | None = None
) -> dict:
    """Returns CapturesPage shape."""
    everything = [r for r, _ in _list_pending()] + [r for r, _ in _list_audit()]
    if source:
        everything = [r for r in everything if r["source"] == source]
    everything.sort(key=lambda r: r["capturedAt"], reverse=True)
    total = len(everything)
    items = everything[offset : offset + limit]
    return {"total": total, "items": items}


def get_capture(capture_id: str) -> dict | None:
    """Returns the full Capture (summary + body + extracted) or None."""
    for record, payload in _list_pending():
        if record["id"] == capture_id:
            return {**record, "body": payload.get("body", ""), "extracted": payload.get("extracted")}
    for record, payload in _list_audit(days_back=7):
        if record["id"] == capture_id:
            return {**record, "body": payload.get("body", ""), "extracted": payload.get("extracted")}
    return None
