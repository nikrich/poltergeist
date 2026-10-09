from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ghostbrain.connectors.whatsapp import allowlist
from ghostbrain.connectors.whatsapp.connector import WhatsAppConnector
from tests.whatsapp_fixtures import make_store

TZ = ZoneInfo("Africa/Johannesburg")
A = "27820000001@s.whatsapp.net"
B = "27820000002@s.whatsapp.net"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=TZ)


def at(days_ago: int, hh: int = 9) -> datetime:
    return (NOW - timedelta(days=days_ago)).replace(hour=hh, minute=0)


class NoVoice:
    def line_for(self, m):
        return "[voice note — transcription pending]", True


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    b = make_store(tmp_path / "ChatStorage.sqlite")
    b.chat(1, A, "Alex", kind=0)
    b.chat(2, B, "Blair", kind=0)
    b.message(10, 1, at(120), text="too old")
    b.message(11, 1, at(5), text="five days ago")
    b.message(12, 1, at(0, 8), text="today one")
    b.message(13, 2, at(0), text="not allowed")
    b.message(14, 1, at(0, 9), type_code=15)  # sticker only
    db = b.close()
    q, s = tmp_path / "queue", tmp_path / "state"
    return db, q, s


def make(db, q, s, *, voice=None, now=NOW):
    return WhatsAppConnector({"store_path": str(db)}, q, s, tz=TZ,
                             now=lambda: now, voice=voice or NoVoice())


def queued(q: Path) -> list[dict]:
    return [json.loads(p.read_text()) for p in sorted((q / "pending").glob("*.json"))]


def test_empty_allowlist_queues_nothing(env):
    db, q, s = env
    assert make(db, q, s).run() == 0
    assert not (q / "pending").exists() or queued(q) == []


def test_first_sync_is_bounded_to_lookback(env):
    db, q, s = env
    allowlist.save(s, {A: {"name": "Alex", "context": None}})
    assert make(db, q, s).run() == 2
    evs = queued(q)
    days = sorted(e["metadata"]["day"] for e in evs)
    assert days == [at(5).date().isoformat(), NOW.date().isoformat()]
    today = next(e for e in evs if e["metadata"]["day"] == NOW.date().isoformat())
    assert today["id"] == f"whatsapp:day:{A}:{NOW.date().isoformat()}"
    assert today["source"] == "whatsapp" and today["type"] == "chat_day"
    assert today["title"] == f"Alex — {NOW.date().isoformat()}"
    assert today["body"] == "**08:00 Alex:** today one"
    assert today["metadata"]["messageCount"] == 1
    assert today["metadata"]["chatKind"] == "direct"
    assert today["metadata"]["context"] is None
    cur = json.loads((s / "whatsapp.cursor.json").read_text())
    assert cur["max_pk"] == 14 and A in cur["chats"]


def test_incremental_rebuilds_whole_changed_day_only(env, tmp_path):
    db, q, s = env
    allowlist.save(s, {A: {"name": "Alex", "context": "work"}})
    make(db, q, s).run()
    for p in (q / "pending").glob("*.json"):
        p.unlink()
    import sqlite3
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE,"
              " ZISFROMME, ZSTANZAID) VALUES (15, 1, ?, 'today two', 0, 1, 'S15')",
              (at(0, 10).timestamp() - 978307200,))
    c.commit()
    c.close()
    assert make(db, q, s).run() == 1
    (ev,) = queued(q)
    assert ev["body"] == "**08:00 Alex:** today one\n**10:00 Me:** today two"
    assert ev["metadata"]["context"] == "work"


def test_no_changes_no_events(env):
    db, q, s = env
    allowlist.save(s, {A: {"name": "Alex", "context": None}})
    make(db, q, s).run()
    for p in (q / "pending").glob("*.json"):
        p.unlink()
    assert make(db, q, s).run() == 0


def test_cursor_not_saved_when_enqueue_fails(env, monkeypatch):
    db, q, s = env
    allowlist.save(s, {A: {"name": "Alex", "context": None}})
    conn = make(db, q, s)

    def boom(event):
        raise OSError("disk full")

    monkeypatch.setattr(conn, "_enqueue", boom)
    with pytest.raises(OSError):
        conn.run()
    assert not (s / "whatsapp.cursor.json").exists()


def test_pending_voice_day_is_rebuilt_next_run(env):
    db, q, s = env
    import sqlite3
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZMESSAGETYPE,"
              " ZISFROMME, ZSTANZAID) VALUES (16, 1, ?, 3, 0, 'S16')",
              (at(5, 11).timestamp() - 978307200,))
    c.commit()
    c.close()
    allowlist.save(s, {A: {"name": "Alex", "context": None}})
    make(db, q, s).run()
    cur = json.loads((s / "whatsapp.cursor.json").read_text())
    assert cur["pending_days"] == [[A, at(5).date().isoformat()]]
    for p in (q / "pending").glob("*.json"):
        p.unlink()

    class Done:
        def line_for(self, m):
            return "🎙 now transcribed", False

    assert make(db, q, s, voice=Done()).run() == 1
    assert "🎙 now transcribed" in queued(q)[0]["body"]
    assert json.loads((s / "whatsapp.cursor.json").read_text())["pending_days"] == []


def test_health_check(env, tmp_path):
    db, q, s = env
    assert make(db, q, s).health_check() is True
    missing = WhatsAppConnector({"store_path": str(tmp_path / "nope.sqlite")}, q, s)
    assert missing.health_check() is False


def test_runner_build_skips_off_macos_or_without_store(env, monkeypatch, tmp_path):
    from ghostbrain.connectors.whatsapp import runner
    db, q, s = env
    monkeypatch.setenv("GHOSTBRAIN_WHATSAPP_STORE", str(db))
    monkeypatch.setattr(runner.sys, "platform", "linux")
    assert runner._build({}, q, s) is None
    monkeypatch.setattr(runner.sys, "platform", "darwin")
    built = runner._build({"whatsapp": {"initial_lookback_days": 7, "voice_max_per_run": 2}}, q, s)
    assert built is not None and built.lookback_days == 7 and built.voice.budget == 2
    monkeypatch.setenv("GHOSTBRAIN_WHATSAPP_STORE", str(tmp_path / "nope.sqlite"))
    assert runner._build({}, q, s) is None


def test_reselected_chat_backfills_messages_sent_while_deselected(env):
    db, q, s = env
    allowlist.save(s, {A: {"name": "Alex", "context": None}})
    make(db, q, s).run()
    allowlist.save(s, {})
    assert make(db, q, s).run() == 0
    import sqlite3
    c = sqlite3.connect(db)
    c.execute("INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE,"
              " ZISFROMME, ZSTANZAID) VALUES (20, 1, ?, 'while away', 0, 0, 'S20')",
              (at(2).timestamp() - 978307200,))
    c.commit()
    c.close()
    for p in (q / "pending").glob("*.json"):
        p.unlink()
    allowlist.save(s, {A: {"name": "Alex", "context": None}})
    assert make(db, q, s).run() == 3
    days = sorted(e["metadata"]["day"] for e in queued(q))
    assert days == [at(5).date().isoformat(), at(2).date().isoformat(),
                    NOW.date().isoformat()]


def test_non_object_cursor_starts_fresh(env):
    db, q, s = env
    allowlist.save(s, {A: {"name": "Alex", "context": None}})
    (s / "whatsapp.cursor.json").write_text("[1]", encoding="utf-8")
    assert make(db, q, s).run() == 2
    assert isinstance(json.loads((s / "whatsapp.cursor.json").read_text()), dict)
    assert not (s / "whatsapp.cursor.json.tmp").exists()
