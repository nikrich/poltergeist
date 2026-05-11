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
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            at_str = event.get("at", "")
            try:
                when = datetime.fromisoformat(at_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when < cutoff:
                continue
            items.append({
                "id": event.get("id", f"audit-{day}-{len(items)}"),
                "source": event.get("source", "unknown"),
                "verb": event.get("verb", "processed"),
                "subject": event.get("subject", ""),
                "atRelative": _relative(when),
                "at": at_str,
            })
    items.sort(key=lambda r: r["at"], reverse=True)
    return items
