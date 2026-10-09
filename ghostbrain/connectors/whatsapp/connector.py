"""WhatsApp connector — one event per allowed chat per local day.

Each run finds chat-days with messages newer than the cursor (or, for a newly
allowed chat, every day in the lookback window) and emits the *whole* day's
transcript, so the worker can overwrite the day note in place.
"""
from __future__ import annotations

import json
import logging
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


class WhatsAppConnector(Connector):
    name = "whatsapp"

    def __init__(self, config: dict, queue_dir: Path, state_dir: Path, *, tz=None,
                 now: Callable[[], datetime] | None = None, voice=None) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.store_path = Path(config.get("store_path") or store.default_store_path())
        self.lookback_days = int(config.get("initial_lookback_days") or DEFAULT_LOOKBACK_DAYS)
        self.tz = tz or store.local_tz()
        self._now = now or (lambda: datetime.now(UTC))
        self.voice = voice or VoiceTranscriber(
            state_dir / "whatsapp" / "voice",
            budget=int(config.get("voice_max_per_run") or DEFAULT_VOICE_MAX_PER_RUN),
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
            return [], cursor
        now = self._now()
        floor = now - timedelta(days=self.lookback_days)
        new = sorted(j for j in allowed if j not in cursor["chats"])
        known = sorted(j for j in allowed if j in cursor["chats"])
        root = store.media_root(self.store_path)
        events: list[dict] = []
        pending: list[list[str]] = []
        with closing(store.open_store(self.store_path)) as conn:
            store.check_schema(conn)
            max_pk = store.max_message_pk(conn)
            dirty = store.dirty_days(conn, new, after_pk=0, since=floor, tz=self.tz)
            dirty |= store.dirty_days(conn, known, after_pk=cursor["max_pk"], since=floor,
                                      tz=self.tz)
            dirty |= {(j, date.fromisoformat(d)) for j, d in cursor["pending_days"]
                      if j in allowed}
            chats = {c.jid: c for c in store.list_chats(conn, tz=self.tz)}
            for jid, day in sorted(dirty):
                chat = chats.get(jid)
                if chat is None:
                    continue
                msgs = store.messages_for_day(conn, jid, day, tz=self.tz, media_root=root)
                rendered = render_day(msgs, self.voice.line_for)
                if rendered.pending:
                    pending.append([jid, day.isoformat()])
                if rendered.lines:
                    events.append(_event(chat, day, msgs, rendered, allowed[jid]))
        stamp = now.isoformat()
        cursor = {
            "max_pk": max_pk,
            "chats": {**cursor["chats"], **{j: {"first_synced_at": stamp} for j in new}},
            "pending_days": pending,
        }
        return events, cursor

    def _cursor_path(self) -> Path:
        return self.state_dir / CURSOR_FILE

    def _load_cursor(self) -> dict:
        base = {"max_pk": 0, "chats": {}, "pending_days": []}
        f = self._cursor_path()
        if f.exists():
            try:
                base.update(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                log.warning("whatsapp cursor unreadable; starting fresh")
        return base

    def _save_cursor(self, cursor: dict) -> None:
        f = self._cursor_path()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cursor, indent=2), encoding="utf-8")


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
