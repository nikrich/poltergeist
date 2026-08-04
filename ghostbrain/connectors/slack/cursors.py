"""Per-channel cursor state for the Slack full-pull connector.

A cursor is the Slack timestamp (``ts``) of the last message we processed
in a channel. The next fetch passes ``oldest=<cursor>`` so we only see new
messages. Persisting cursors per (workspace, channel) lets us pull from
hundreds of channels incrementally without replaying history.

State file: ``~/.ghostbrain/state/slack_cursors.<workspace_slug>.json``
Shape::

    {
      "version": 1,
      "channels": {
        "C12345678": {
          "name": "engineering",
          "last_ts": "1778250000.123456",
          "updated_at": "2026-05-14T08:00:00+00:00"
        }
      }
    }

Cursor format is the raw Slack ``ts`` string — not parsed to float — so
microsecond precision is preserved verbatim (Slack uses ``ts`` as an
identity key, not just a timestamp).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.slack.cursors")

SCHEMA_VERSION = 1


@dataclass
class CursorState:
    workspace_slug: str
    path: Path
    channels: dict[str, dict] = field(default_factory=dict)

    def get(self, channel_id: str) -> str | None:
        return (self.channels.get(channel_id) or {}).get("last_ts")

    def set(self, channel_id: str, *, last_ts: str, name: str) -> None:
        self.channels[channel_id] = {
            "name": name,
            "last_ts": last_ts,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": SCHEMA_VERSION, "channels": self.channels}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def cursor_path(state_dir: Path, workspace_slug: str) -> Path:
    return state_dir / f"slack_cursors.{workspace_slug}.json"


def load_cursors(state_dir: Path, workspace_slug: str) -> CursorState:
    """Load cursor state for a workspace. Returns an empty state on
    first run or if the file is corrupt — corruption logged but never
    propagates, so a bad cursor file doesn't block ingestion."""
    path = cursor_path(state_dir, workspace_slug)
    if not path.exists():
        return CursorState(workspace_slug=workspace_slug, path=path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.exception("slack cursor file corrupt; starting fresh: %s", path)
        return CursorState(workspace_slug=workspace_slug, path=path)
    channels = raw.get("channels") or {}
    if not isinstance(channels, dict):
        channels = {}
    return CursorState(
        workspace_slug=workspace_slug,
        path=path,
        channels={k: v for k, v in channels.items() if isinstance(v, dict)},
    )
