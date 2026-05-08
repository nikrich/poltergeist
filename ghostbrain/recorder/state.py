"""Persisted recorder state — survives daemon restarts.

Tracks:
- ``active``: a recording in flight (PID, WAV, scheduled-end ISO).
- ``processed``: event ids we've already recorded so we don't double-record
  if the daemon restarts mid-meeting or polls overlapping windows.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("ghostbrain.recorder.state")

PROCESSED_RETENTION_DAYS = 14  # purge older entries to keep state file small


def state_dir() -> Path:
    raw = os.environ.get("GHOSTBRAIN_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ghostbrain" / "state").resolve()


def state_file() -> Path:
    return state_dir() / "recorder.json"


@dataclasses.dataclass
class ActiveRecording:
    event_id: str
    title: str
    context: str
    pid: int
    wav_path: str
    started_at: str       # ISO; when ffmpeg launched
    scheduled_end: str    # ISO; meeting end + grace

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActiveRecording":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})


@dataclasses.dataclass
class RecorderState:
    active: ActiveRecording | None = None
    # event_id → ISO timestamp recorded
    processed: dict[str, str] = dataclasses.field(default_factory=dict)


def load() -> RecorderState:
    f = state_file()
    if not f.exists():
        return RecorderState()
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("recorder state unreadable, starting fresh: %s", e)
        return RecorderState()
    active_raw = raw.get("active")
    return RecorderState(
        active=(ActiveRecording.from_dict(active_raw) if active_raw else None),
        processed=dict(raw.get("processed") or {}),
    )


def save(state: RecorderState) -> None:
    """Atomic write so the daemon never sees a half-written state."""
    state_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "active": state.active.to_dict() if state.active else None,
        "processed": state.processed,
    }
    target = state_file()
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".recorder.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_name, target)
        os.chmod(target, 0o600)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def prune_processed(state: RecorderState, *, retention_days: int = PROCESSED_RETENTION_DAYS) -> None:
    """Drop processed entries older than ``retention_days``."""
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    keep: dict[str, str] = {}
    for event_id, ts_iso in state.processed.items():
        try:
            ts = datetime.fromisoformat(ts_iso).timestamp()
        except ValueError:
            continue
        if ts >= cutoff:
            keep[event_id] = ts_iso
    state.processed = keep
