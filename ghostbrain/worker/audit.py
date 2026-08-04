"""Append-only audit log. Lines are JSON, one per event."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ghostbrain.paths import audit_dir


def audit_log(event_type: str, event_id: str | None = None, **fields: Any) -> None:
    """Append a structured line to today's audit log.

    File: ``<vault>/90-meta/audit/YYYY-MM-DD.jsonl``
    """
    now = datetime.now(timezone.utc)
    record: dict[str, Any] = {
        "ts": now.isoformat(),
        "event_type": event_type,
    }
    if event_id is not None:
        record["event_id"] = event_id
    record.update(fields)

    log_dir = audit_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{now.strftime('%Y-%m-%d')}.jsonl"
    with log_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
