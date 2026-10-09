"""WhatsApp connector — one event per allowed chat per local day.

Each run finds chat-days with messages newer than the cursor (or, for a newly
allowed chat, every day in the lookback window) and emits the *whole* day's
transcript, so the worker can overwrite the day note in place. Today and
yesterday are also re-rendered every run and emitted when their transcript
hash changed, which catches edits and late media downloads (no new PK).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.whatsapp import allowlist, store
from ghostbrain.connectors.whatsapp.render import RenderedDay, render_day
from ghostbrain.connectors.whatsapp.voice import VoiceTranscriber

log = logging.getLogger("ghostbrain.connectors.whatsapp")

DEFAULT_LOOKBACK_DAYS = 90
DEFAULT_VOICE_MAX_PER_RUN = 40
CURSOR_FILE = "whatsapp.cursor.json"


def _int_or(value, default: int) -> int:
    """Default only when the key is missing/None, so a configured 0 is honoured."""
    return default if value is None else int(value)


class WhatsAppConnector(Connector):
    name = "whatsapp"

    def __init__(self, config: dict, queue_dir: Path, state_dir: Path, *, tz=None,
                 now: Callable[[], datetime] | None = None, voice=None) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.store_path = Path(config.get("store_path") or store.default_store_path())
        self.lookback_days = _int_or(config.get("initial_lookback_days"), DEFAULT_LOOKBACK_DAYS)
        self.tz = tz or store.local_tz()
        self._now = now or (lambda: datetime.now(UTC))
        self.voice = voice or VoiceTranscriber(
            state_dir / "whatsapp" / "voice",
            budget=_int_or(config.get("voice_max_per_run"), DEFAULT_VOICE_MAX_PER_RUN),
        )

    def health_check(self) -> bool:
        try:
            with closing(store.open_store(self.store_path)) as conn:
                store.check_schema(conn)
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("whatsapp health check failed: %s", e)
            return False

    def normalize(self, raw: dict) -> dict:
        return raw

    def fetch(self, since: datetime) -> list[dict]:
        events, _ = self._collect()
        return events

    def run(self) -> int:
        events, cursor = self._collect()
        for event in events:
            self._enqueue(event)
        self._save_cursor(cursor)  # last: a crash replays dirty days instead of losing them
        return len(events)

    def _collect(self) -> tuple[list[dict], dict]:
        allowed = allowlist.load(self.state_dir)
        cursor = self._load_cursor()
        if not allowed:
            log.info("whatsapp: no chats selected; pick chats in Connectors → WhatsApp")
            return [], {**cursor, "chats": {}}
        now = self._now()
        # Day-aligned so lookback 0 means "today onward" (events are whole days).
        floor = (now - timedelta(days=self.lookback_days)).astimezone(self.tz).replace(
            hour=0, minute=0, second=0, microsecond=0)
        today = now.astimezone(self.tz).date()
        recent_days = _recent(today)
        recent = {(j, d) for j in allowed for d in recent_days if d >= floor.date()}
        new = sorted(j for j in allowed if j not in cursor["chats"])
        known = sorted(j for j in allowed if j in cursor["chats"])
        root = store.media_root(self.store_path)
        events: list[dict] = []
        pending: list[list[str]] = []
        hashes: dict[str, str] = {}
        with closing(store.open_store(self.store_path)) as conn:
            store.check_schema(conn)
            max_pk = store.max_message_pk(conn)
            dirty = store.dirty_days(conn, new, after_pk=0, since=floor, tz=self.tz)
            dirty |= store.dirty_days(conn, known, after_pk=cursor["max_pk"], since=floor,
                                      tz=self.tz)
            dirty |= {(j, date.fromisoformat(d)) for j, d in cursor["pending_days"]
                      if j in allowed}
            chats = {c.jid: c for c in store.list_chats(conn, tz=self.tz)}
            for jid, day in sorted(dirty | recent):
                chat = chats.get(jid)
                if chat is None:
                    continue
                msgs = store.messages_for_day(conn, jid, day, tz=self.tz, media_root=root)
                rendered = render_day(msgs, self.voice.line_for)
                key = f"{jid}|{day.isoformat()}"
                hashes[key] = hashlib.sha256(rendered.body.encode("utf-8")).hexdigest()
                if rendered.pending:
                    pending.append([jid, day.isoformat()])
                # A recent day that is not PK-dirty is only re-sent when it changed.
                changed = (jid, day) in dirty or cursor["day_hashes"].get(key) != hashes[key]
                if rendered.lines and changed:
                    events.append(_event(chat, day, msgs, rendered, allowed[jid]))
        stamp = now.isoformat()
        cursor = {
            "max_pk": max_pk,
            # Only currently-allowed chats stay "known": a deselected chat that is
            # re-added counts as new and gets the lookback backfill.
            "chats": {
                **{j: v for j, v in cursor["chats"].items() if j in allowed},
                **{j: {"first_synced_at": stamp} for j in new},
            },
            "pending_days": pending,
            "day_hashes": hashes,
        }
        return events, cursor

    def _cursor_path(self) -> Path:
        return self.state_dir / CURSOR_FILE

    def _load_cursor(self) -> dict:
        loaded: object = None
        f = self._cursor_path()
        if f.exists():
            try:
                loaded = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                loaded = None
            if not isinstance(loaded, dict):
                log.warning("whatsapp cursor unreadable; starting fresh")
        return _valid_cursor(loaded if isinstance(loaded, dict) else {})

    def _save_cursor(self, cursor: dict) -> None:
        # Hashes only matter for the recent window; keep the file tiny.
        recent = {d.isoformat() for d in _recent(self._now().astimezone(self.tz).date())}
        cursor = {**cursor, "day_hashes": {
            k: v for k, v in cursor.get("day_hashes", {}).items()
            if k.rpartition("|")[2] in recent}}
        f = self._cursor_path()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(cursor, indent=2), encoding="utf-8")
        os.replace(tmp, f)


def _recent(today: date) -> set[date]:
    """The always-rechecked window: today and yesterday (local dates)."""
    return {today, today - timedelta(days=1)}


def _valid_cursor(raw: dict) -> dict:
    """Coerce each cursor field to its expected shape; bad fields reset to defaults."""
    max_pk = raw.get("max_pk")
    chats = raw.get("chats")
    pending = raw.get("pending_days")
    hashes = raw.get("day_hashes")
    return {
        "max_pk": max_pk if isinstance(max_pk, int) and not isinstance(max_pk, bool) else 0,
        "chats": chats if isinstance(chats, dict) else {},
        "pending_days": ([p for p in pending if _valid_pending(p)]
                         if isinstance(pending, list) else []),
        "day_hashes": ({k: v for k, v in hashes.items() if isinstance(v, str)}
                       if isinstance(hashes, dict) else {}),
    }


def _valid_pending(entry: object) -> bool:
    if not (isinstance(entry, list) and len(entry) == 2
            and all(isinstance(x, str) for x in entry)):
        return False
    try:
        date.fromisoformat(entry[1])
    except ValueError:
        return False
    return True


def _event(chat: store.Chat, day: date, msgs: list[store.Message], rendered: RenderedDay,
           entry: dict) -> dict:
    return {
        "id": f"whatsapp:day:{chat.jid}:{day.isoformat()}",
        "source": "whatsapp",
        "type": "chat_day",
        "timestamp": msgs[-1].at.astimezone(UTC).isoformat(),
        "title": f"{chat.name} — {day.isoformat()}",
        "body": rendered.body,
        "metadata": {
            "chatJid": chat.jid,
            "chatName": chat.name,
            "chatKind": chat.kind,
            "day": day.isoformat(),
            "participants": rendered.participants,
            "messageCount": rendered.lines,
            "voiceNotes": rendered.voice_notes,
            "context": entry.get("context"),
        },
    }
