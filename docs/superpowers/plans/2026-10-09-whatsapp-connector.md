# WhatsApp Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the user's chosen WhatsApp chats from the macOS WhatsApp app's local database into the vault. Each chat gets one note per local day, with voice notes transcribed locally.

**Architecture:** A read-only SQLite reader (`store.py`) isolates WhatsApp's undocumented schema. A pure renderer (`render.py`) turns one chat-day of messages into a markdown transcript, and `voice.py` turns voice notes into cached whisper transcripts. The connector (`connector.py`) works out which chat-days changed since a message-PK cursor and emits one event per chat-day with the full transcript. The existing worker writes it to a stable filename, so later runs overwrite it in place. A sidecar endpoint plus a renderer picker manage the opt-in allowlist.

**Tech Stack:** Python 3.11+ (stdlib `sqlite3`, `subprocess`), FastAPI, pytest; Electron renderer with React, TanStack Query, Vitest and RTL.

**Spec:** `docs/superpowers/specs/2026-10-09-whatsapp-connector-design.md`

**Worktree:** all work happens in `/Users/jannik/development/nikrich/ghost-brain-wa` on branch `docs/whatsapp-connector-spec`. Rename it to `feat/whatsapp-connector` before Task 1:

```bash
cd /Users/jannik/development/nikrich/ghost-brain-wa && git branch -m feat/whatsapp-connector
```

Every command below starts with `cd /Users/jannik/development/nikrich/ghost-brain-wa &&`. Subagents must use that absolute path and run `git rev-parse --abbrev-ref HEAD` first to confirm `feat/whatsapp-connector`.

## Global Constraints

- macOS only. The store path is `~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/ChatStorage.sqlite`, overridable with the `GHOSTBRAIN_WHATSAPP_STORE` env var.
- The store is **never written to**. Open it with `mode=ro` URIs and `PRAGMA query_only=1`.
- Core Data epoch offset: `978307200`, added to `ZMESSAGEDATE` to get Unix seconds.
- Chats in scope: `ZSESSIONTYPE IN (0, 1)` (direct, group) and `COALESCE(ZREMOVED, 0) = 0`.
- Message types kept (spec table): `0` text, `1` image, `2` video, `3` voice, `4` contact card, `5` location, `7` link, `8` document, `11` gif. All other codes are dropped.
- Opt-in: an empty allowlist means 0 events. `initial_lookback_days` defaults to `90` and `voice_max_per_run` to `40`.
- The context falls back in this order: per-chat override, then `routing.yaml` `whatsapp.default_context`, then `personal`. A candidate counts only if it's in `routing_config.contexts()`; if none is, use `contexts()[0]`.
- The connector id is `whatsapp` everywhere (scheduler job, state files, `_DISPLAY`, catalog card, provider registration).
- Never put real names, numbers or message text in tests, fixtures, logs or commits. Fixtures are synthetic.
- The repo is public, so `tests/test_no_hardcoded_contexts.py` must keep passing. Use only `personal` / `work` / neutral placeholders as context names.
- Run Python tests with `.venv/bin/pytest` from the worktree. If `.venv` is missing, create it with `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`. Run desktop tests with `cd desktop && npx vitest run <file>`, and the type check with `cd desktop && npm run typecheck` (`tsc --noEmit` is a no-op here).
- Never run the full pytest suite without `GHOSTBRAIN_STATE_DIR` sandboxed, because it can clobber recorder state. The `vault` fixture handles the vault, and each WhatsApp test sets `GHOSTBRAIN_STATE_DIR` to a `tmp_path`.

## Review Focus

1. **Messages around local midnight.** A message at 23:59 and one at 00:01 local must land in different day notes. The bucketing uses the user's timezone, not UTC. Pinned in Task 1 (`test_day_bucketing_uses_local_timezone`).
2. **A chat renamed between runs.** The new day note uses the new name, and older notes keep the old filename. Both stay unique because the JID suffix is stable. Pinned in Task 6 (`test_filename_stable_across_rebuilds_and_unique_per_jid`).
3. **A voice note downloaded later.** First it renders as `not downloaded`; after the user plays it in WhatsApp, the file appears. No new message PK appears, so that day isn't rebuilt automatically, and that's accepted. The test pins that the placeholder is never cached as a transcript. Pinned in Task 3 (`test_not_downloaded_is_not_cached`).
4. **WhatsApp running and writing during a read.** The WAL is live. A read-only connection with a busy timeout must not raise and must not block WhatsApp. Pinned in Task 1 (`test_open_store_reads_while_writer_holds_wal`).
5. **Two group chats whose JIDs share a prefix.** Group JIDs all start `120363…`. The filename suffix uses the *last* 12 digits so they don't collide. Pinned in Task 6 (same test as #2).

---

### Task 1: Store reader and fixture builder

**Files:**
- Create: `ghostbrain/connectors/whatsapp/__init__.py`
- Create: `ghostbrain/connectors/whatsapp/store.py`
- Create: `tests/whatsapp_fixtures.py`
- Test: `tests/test_whatsapp_store.py`

**Interfaces:**
- Produces:
  - `store.CORE_DATA_EPOCH: int`
  - `store.StoreSchemaError(RuntimeError)`
  - `store.Chat(pk:int, jid:str, name:str, kind:str, last_message_at:datetime|None, message_count:int)`
  - `store.Message(pk:int, stanza_id:str, at:datetime, sender:str, is_from_me:bool, type_code:int, text:str|None, caption:str|None, media_path:Path|None)`
  - `store.default_store_path() -> Path`
  - `store.open_store(path:Path) -> sqlite3.Connection`
  - `store.check_schema(conn) -> None`
  - `store.list_chats(conn, *, tz) -> list[Chat]`
  - `store.max_message_pk(conn) -> int`
  - `store.dirty_days(conn, jids:list[str], *, after_pk:int, since:datetime, tz) -> set[tuple[str, date]]`
  - `store.messages_for_day(conn, jid:str, day:date, *, tz, media_root:Path) -> list[Message]`
  - `store.media_root(store_path:Path) -> Path`
  - `store.local_tz() -> tzinfo`
- Test helper `tests/whatsapp_fixtures.py` produces `make_store(path:Path) -> StoreBuilder`, with `.chat(...)`, `.member(...)`, `.push_name(...)`, `.message(...)`, `.media(...)`, `.close()`.

- [ ] **Step 1: Write the fixture builder** (`tests/whatsapp_fixtures.py`)

  The DDL is copied from the real store's `.schema` output (2026-10-09). Only the tables the connector reads are included, with every real column so `check_schema` sees a realistic store.

```python
"""Synthetic WhatsApp ChatStorage.sqlite builder for tests.

DDL copied from the real macOS store's `.schema` (2026-10-09) for the five
tables the connector reads. No real data — every name/number is invented.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

CORE_DATA_EPOCH = 978307200

DDL = [
    """CREATE TABLE ZWACHATSESSION ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZARCHIVED INTEGER, ZCONTACTABID INTEGER, ZFLAGS INTEGER, ZHIDDEN INTEGER, ZIDENTITYVERIFICATIONEPOCH INTEGER, ZIDENTITYVERIFICATIONSTATE INTEGER, ZMESSAGECOUNTER INTEGER, ZREMOVED INTEGER, ZSESSIONTYPE INTEGER, ZSPOTLIGHTSTATUS INTEGER, ZUNREADCOUNT INTEGER, ZGROUPINFO INTEGER, ZLASTMESSAGE INTEGER, ZPROPERTIES INTEGER, ZLASTMESSAGEDATE TIMESTAMP, ZLOCATIONSHARINGENDDATE TIMESTAMP, ZCONTACTIDENTIFIER VARCHAR, ZCONTACTJID VARCHAR, ZETAG VARCHAR, ZLASTMESSAGETEXT VARCHAR, ZPARTNERNAME VARCHAR, ZSAVEDINPUT VARCHAR )""",
    """CREATE TABLE ZWAMESSAGE ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZCHILDMESSAGESDELIVEREDCOUNT INTEGER, ZCHILDMESSAGESPLAYEDCOUNT INTEGER, ZCHILDMESSAGESREADCOUNT INTEGER, ZDATAITEMVERSION INTEGER, ZDOCID INTEGER, ZENCRETRYCOUNT INTEGER, ZFILTEREDRECIPIENTCOUNT INTEGER, ZFLAGS INTEGER, ZGROUPEVENTTYPE INTEGER, ZISFROMME INTEGER, ZMESSAGEERRORSTATUS INTEGER, ZMESSAGESTATUS INTEGER, ZMESSAGETYPE INTEGER, ZSORT INTEGER, ZSPOTLIGHTSTATUS INTEGER, ZSTARRED INTEGER, ZCHATSESSION INTEGER, ZGROUPMEMBER INTEGER, ZLASTSESSION INTEGER, ZMEDIAITEM INTEGER, ZMESSAGEINFO INTEGER, ZPARENTMESSAGE INTEGER, ZMESSAGEDATE TIMESTAMP, ZSENTDATE TIMESTAMP, ZFROMJID VARCHAR, ZMEDIASECTIONID VARCHAR, ZPHASH VARCHAR, ZPUSHNAME VARCHAR, ZSTANZAID VARCHAR, ZTEXT VARCHAR, ZTOJID VARCHAR )""",
    """CREATE TABLE ZWAMEDIAITEM ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZCLOUDSTATUS INTEGER, ZFILESIZE INTEGER, ZMEDIAORIGIN INTEGER, ZMOVIEDURATION INTEGER, ZMESSAGE INTEGER, ZASPECTRATIO FLOAT, ZHACCURACY FLOAT, ZLATITUDE FLOAT, ZLONGITUDE FLOAT, ZMEDIAURLDATE TIMESTAMP, ZAUTHORNAME VARCHAR, ZCOLLECTIONNAME VARCHAR, ZMEDIALOCALPATH VARCHAR, ZMEDIAURL VARCHAR, ZTHUMBNAILLOCALPATH VARCHAR, ZTITLE VARCHAR, ZVCARDNAME VARCHAR, ZVCARDSTRING VARCHAR, ZXMPPTHUMBPATH VARCHAR, ZMEDIAKEY BLOB, ZMETADATA BLOB )""",
    """CREATE TABLE ZWAGROUPMEMBER ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZCONTACTABID INTEGER, ZISACTIVE INTEGER, ZISADMIN INTEGER, ZSENDERKEYSENT INTEGER, ZCHATSESSION INTEGER, ZRECENTGROUPCHAT INTEGER, ZCONTACTIDENTIFIER VARCHAR, ZCONTACTNAME VARCHAR, ZFIRSTNAME VARCHAR, ZMEMBERJID VARCHAR )""",
    """CREATE TABLE ZWAPROFILEPUSHNAME ( Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZJID VARCHAR, ZPUSHNAME VARCHAR )""",
]


def core(dt: datetime) -> float:
    """Aware datetime -> Core Data seconds."""
    return dt.timestamp() - CORE_DATA_EPOCH


class StoreBuilder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=wal")
        for stmt in DDL:
            self.conn.execute(stmt)

    def chat(self, pk: int, jid: str, name: str | None, *, kind: int = 0,
             removed: int = 0, last: datetime | None = None) -> int:
        self.conn.execute(
            "INSERT INTO ZWACHATSESSION (Z_PK, ZCONTACTJID, ZPARTNERNAME, ZSESSIONTYPE,"
            " ZREMOVED, ZLASTMESSAGEDATE) VALUES (?,?,?,?,?,?)",
            (pk, jid, name, kind, removed, core(last) if last else None),
        )
        return pk

    def member(self, pk: int, chat_pk: int, jid: str, *, contact_name: str | None = None,
               first_name: str | None = None) -> int:
        self.conn.execute(
            "INSERT INTO ZWAGROUPMEMBER (Z_PK, ZCHATSESSION, ZMEMBERJID, ZCONTACTNAME, ZFIRSTNAME)"
            " VALUES (?,?,?,?,?)",
            (pk, chat_pk, jid, contact_name, first_name),
        )
        return pk

    def push_name(self, jid: str, name: str) -> None:
        self.conn.execute("INSERT INTO ZWAPROFILEPUSHNAME (ZJID, ZPUSHNAME) VALUES (?,?)", (jid, name))

    def media(self, pk: int, *, local_path: str | None = None, title: str | None = None) -> int:
        self.conn.execute(
            "INSERT INTO ZWAMEDIAITEM (Z_PK, ZMEDIALOCALPATH, ZTITLE) VALUES (?,?,?)",
            (pk, local_path, title),
        )
        return pk

    def message(self, pk: int, chat_pk: int, at: datetime, *, text: str | None = None,
                type_code: int = 0, from_me: bool = False, from_jid: str | None = None,
                push: str | None = None, member_pk: int | None = None,
                media_pk: int | None = None, stanza: str | None = None) -> int:
        self.conn.execute(
            "INSERT INTO ZWAMESSAGE (Z_PK, ZCHATSESSION, ZMESSAGEDATE, ZTEXT, ZMESSAGETYPE,"
            " ZISFROMME, ZFROMJID, ZPUSHNAME, ZGROUPMEMBER, ZMEDIAITEM, ZSTANZAID)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pk, chat_pk, core(at), text, type_code, 1 if from_me else 0, from_jid, push,
             member_pk, media_pk, stanza or f"STANZA{pk}"),
        )
        return pk

    def close(self) -> Path:
        self.conn.commit()
        self.conn.close()
        return self.path


def make_store(path: Path) -> StoreBuilder:
    return StoreBuilder(path)
```

- [ ] **Step 2: Write the failing store tests** (`tests/test_whatsapp_store.py`)

```python
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from ghostbrain.connectors.whatsapp import store
from tests.whatsapp_fixtures import make_store

TZ = ZoneInfo("Africa/Johannesburg")  # UTC+2, no DST
DIRECT = "27820000001@s.whatsapp.net"
GROUP = "120363000000000001@g.us"


def at(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


@pytest.fixture
def db(tmp_path: Path) -> Path:
    b = make_store(tmp_path / "ChatStorage.sqlite")
    b.chat(1, DIRECT, "Alex Example", kind=0, last=at(2026, 10, 9, 8, 0))
    b.chat(2, GROUP, "Book Club", kind=1, last=at(2026, 10, 9, 9, 0))
    b.chat(3, "status@broadcast", "Status", kind=3)
    b.chat(4, "27820000009@s.whatsapp.net", "Gone", kind=0, removed=1)
    b.chat(5, "27820000005@s.whatsapp.net", None, kind=0)
    b.member(10, 2, "111@lid", contact_name="Sam Contact")
    b.member(11, 2, "222@lid", first_name="Robin")
    b.member(12, 2, "333@lid")
    b.member(13, 2, "444@lid")
    b.push_name("333@lid", "Pushy")
    b.media(50, local_path="Media/x/voice.opus")
    b.media(51, local_path=None, title="sunset")
    b.message(100, 1, at(2026, 10, 8, 23, 59), text="late")
    b.message(101, 1, at(2026, 10, 9, 0, 1), text="early", from_me=True)
    b.message(102, 2, at(2026, 10, 9, 9, 0), text="hi", member_pk=10, from_jid=GROUP)
    b.message(103, 2, at(2026, 10, 9, 9, 1), text="yo", member_pk=11, from_jid=GROUP)
    b.message(104, 2, at(2026, 10, 9, 9, 2), text="hey", member_pk=12, from_jid=GROUP)
    b.message(105, 2, at(2026, 10, 9, 9, 3), text="sup", member_pk=13, from_jid=GROUP, push="MsgPush")
    b.message(106, 1, at(2026, 10, 9, 10, 0), type_code=3, media_pk=50)
    b.message(107, 1, at(2026, 10, 9, 10, 5), type_code=1, media_pk=51)
    b.message(108, 1, at(2025, 1, 1, 12, 0), text="ancient")
    return b.close()


@pytest.fixture
def conn(db: Path):
    c = store.open_store(db)
    yield c
    c.close()


def test_default_store_path_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_WHATSAPP_STORE", str(tmp_path / "x.sqlite"))
    assert store.default_store_path() == tmp_path / "x.sqlite"


def test_default_store_path_is_group_container(monkeypatch):
    monkeypatch.delenv("GHOSTBRAIN_WHATSAPP_STORE", raising=False)
    p = store.default_store_path()
    assert p.parts[-2:] == ("group.net.whatsapp.WhatsApp.shared", "ChatStorage.sqlite")


def test_open_store_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        store.open_store(tmp_path / "nope.sqlite")


def test_open_store_is_read_only(conn):
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM ZWAMESSAGE")


def test_open_store_reads_while_writer_holds_wal(db):
    writer = sqlite3.connect(db)
    writer.execute("BEGIN IMMEDIATE")
    writer.execute("UPDATE ZWAMESSAGE SET ZTEXT='changed' WHERE Z_PK=100")
    try:
        c = store.open_store(db)
        assert store.max_message_pk(c) == 108
        c.close()
    finally:
        writer.rollback()
        writer.close()


def test_check_schema_passes_on_real_ddl(conn):
    store.check_schema(conn)


def test_check_schema_names_missing_column(tmp_path):
    p = tmp_path / "bad.sqlite"
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE ZWACHATSESSION (Z_PK INTEGER PRIMARY KEY, ZCONTACTJID VARCHAR)")
    c.commit()
    c.close()
    ro = store.open_store(p)
    with pytest.raises(store.StoreSchemaError) as e:
        store.check_schema(ro)
    assert "ZWACHATSESSION.ZPARTNERNAME" in str(e.value)
    assert "ZWAMESSAGE" in str(e.value)


def test_list_chats_scope_and_fallback_name(conn):
    chats = {c.jid: c for c in store.list_chats(conn, tz=TZ)}
    assert set(chats) == {DIRECT, GROUP, "27820000005@s.whatsapp.net"}
    assert chats[DIRECT].kind == "direct" and chats[DIRECT].name == "Alex Example"
    assert chats[GROUP].kind == "group"
    assert chats[DIRECT].message_count == 5
    assert chats["27820000005@s.whatsapp.net"].name == "+27820000005"
    assert chats[DIRECT].last_message_at == at(2026, 10, 9, 8, 0)


def test_day_bucketing_uses_local_timezone(conn):
    days = store.dirty_days(conn, [DIRECT], after_pk=0,
                            since=at(2026, 10, 1, 0, 0), tz=TZ)
    assert days == {(DIRECT, date(2026, 10, 8)), (DIRECT, date(2026, 10, 9))}


def test_dirty_days_respects_after_pk_and_since(conn):
    assert store.dirty_days(conn, [DIRECT, GROUP], after_pk=105,
                            since=at(2026, 10, 1, 0, 0), tz=TZ) == {(DIRECT, date(2026, 10, 9))}
    assert store.dirty_days(conn, [DIRECT], after_pk=0,
                            since=at(2024, 1, 1, 0, 0), tz=TZ) >= {(DIRECT, date(2025, 1, 1))}
    assert store.dirty_days(conn, [], after_pk=0, since=at(2024, 1, 1, 0, 0), tz=TZ) == set()


def test_messages_for_day_order_senders_media(conn, tmp_path):
    root = tmp_path / "Message"
    msgs = store.messages_for_day(conn, DIRECT, date(2026, 10, 9), tz=TZ, media_root=root)
    assert [m.pk for m in msgs] == [101, 106, 107]
    assert msgs[0].sender == "Me" and msgs[0].is_from_me
    assert msgs[1].sender == "Alex Example"
    assert msgs[1].media_path == root / "Media/x/voice.opus"
    assert msgs[2].media_path is None and msgs[2].caption == "sunset"
    assert msgs[0].at == at(2026, 10, 9, 0, 1)
    assert msgs[0].stanza_id == "STANZA101"


def test_group_sender_resolution_order(conn, tmp_path):
    msgs = store.messages_for_day(conn, GROUP, date(2026, 10, 9), tz=TZ, media_root=tmp_path)
    assert [m.sender for m in msgs] == ["Sam Contact", "Robin", "Pushy", "MsgPush"]


def test_media_root_is_message_dir(tmp_path):
    assert store.media_root(tmp_path / "ChatStorage.sqlite") == tmp_path / "Message"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/test_whatsapp_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.connectors.whatsapp'`

- [ ] **Step 4: Implement** `ghostbrain/connectors/whatsapp/__init__.py`:

```python
"""WhatsApp connector — see docs/superpowers/specs/2026-10-09-whatsapp-connector-design.md."""
```

and `ghostbrain/connectors/whatsapp/store.py`:

```python
"""Read-only access to the macOS WhatsApp store (ChatStorage.sqlite).

All WhatsApp-specific SQL lives here — nothing else in the codebase touches
the schema. The store is Core Data: dates are seconds since 2001-01-01 UTC.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from pathlib import Path

CORE_DATA_EPOCH = 978307200

_CONTAINER = (Path.home() / "Library" / "Group Containers"
              / "group.net.whatsapp.WhatsApp.shared")

REQUIRED_COLUMNS: dict[str, set[str]] = {
    "ZWACHATSESSION": {"Z_PK", "ZCONTACTJID", "ZPARTNERNAME", "ZSESSIONTYPE", "ZREMOVED",
                       "ZLASTMESSAGEDATE"},
    "ZWAMESSAGE": {"Z_PK", "ZCHATSESSION", "ZMESSAGEDATE", "ZISFROMME", "ZTEXT",
                   "ZMESSAGETYPE", "ZFROMJID", "ZPUSHNAME", "ZGROUPMEMBER", "ZMEDIAITEM",
                   "ZSTANZAID"},
    "ZWAMEDIAITEM": {"Z_PK", "ZMEDIALOCALPATH", "ZTITLE"},
    "ZWAGROUPMEMBER": {"Z_PK", "ZCONTACTNAME", "ZFIRSTNAME", "ZMEMBERJID"},
    "ZWAPROFILEPUSHNAME": {"ZJID", "ZPUSHNAME"},
}

_KINDS = {0: "direct", 1: "group"}


class StoreSchemaError(RuntimeError):
    """The store no longer has the tables/columns this connector reads."""


@dataclass(frozen=True)
class Chat:
    pk: int
    jid: str
    name: str
    kind: str  # "direct" | "group"
    last_message_at: datetime | None
    message_count: int


@dataclass(frozen=True)
class Message:
    pk: int
    stanza_id: str
    at: datetime
    sender: str
    is_from_me: bool
    type_code: int
    text: str | None
    caption: str | None
    media_path: Path | None  # absolute; None when WhatsApp never downloaded it


def default_store_path() -> Path:
    raw = os.environ.get("GHOSTBRAIN_WHATSAPP_STORE")
    if raw:
        return Path(raw).expanduser()
    return _CONTAINER / "ChatStorage.sqlite"


def media_root(store_path: Path) -> Path:
    return store_path.parent / "Message"


def local_tz() -> tzinfo:
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def open_store(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=1")
    return conn


def check_schema(conn: sqlite3.Connection) -> None:
    missing: list[str] = []
    for table, cols in REQUIRED_COLUMNS.items():
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            missing.append(table)
            continue
        missing += [f"{table}.{c}" for c in sorted(cols - have)]
    if missing:
        raise StoreSchemaError("WhatsApp store schema changed; missing: " + ", ".join(missing))


def _to_dt(core_seconds: float, tz: tzinfo) -> datetime:
    return datetime.fromtimestamp(core_seconds + CORE_DATA_EPOCH, tz=timezone.utc).astimezone(tz)


def _core(dt: datetime) -> float:
    return dt.timestamp() - CORE_DATA_EPOCH


def _day_bounds(day: date, tz: tzinfo) -> tuple[float, float]:
    start = datetime.combine(day, time.min, tzinfo=tz)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz)
    return _core(start), _core(end)


def _jid_label(jid: str | None) -> str:
    if not jid:
        return "Unknown"
    local, _, domain = jid.partition("@")
    if domain == "s.whatsapp.net" and local.isdigit():
        return f"+{local}"
    return local


def list_chats(conn: sqlite3.Connection, *, tz: tzinfo) -> list[Chat]:
    rows = conn.execute(
        "SELECT c.Z_PK pk, c.ZCONTACTJID jid, c.ZPARTNERNAME name, c.ZSESSIONTYPE st,"
        " c.ZLASTMESSAGEDATE last,"
        " (SELECT COUNT(*) FROM ZWAMESSAGE m WHERE m.ZCHATSESSION = c.Z_PK) n"
        " FROM ZWACHATSESSION c"
        " WHERE c.ZSESSIONTYPE IN (0, 1) AND COALESCE(c.ZREMOVED, 0) = 0"
        " AND c.ZCONTACTJID IS NOT NULL"
        " ORDER BY c.ZLASTMESSAGEDATE DESC"
    ).fetchall()
    return [
        Chat(pk=r["pk"], jid=r["jid"], name=r["name"] or _jid_label(r["jid"]),
             kind=_KINDS[r["st"]],
             last_message_at=_to_dt(r["last"], tz) if r["last"] is not None else None,
             message_count=r["n"])
        for r in rows
    ]


def max_message_pk(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COALESCE(MAX(Z_PK), 0) FROM ZWAMESSAGE").fetchone()[0])


def dirty_days(conn: sqlite3.Connection, jids: list[str], *, after_pk: int,
               since: datetime, tz: tzinfo) -> set[tuple[str, date]]:
    if not jids:
        return set()
    marks = ",".join("?" * len(jids))
    rows = conn.execute(
        "SELECT c.ZCONTACTJID jid, m.ZMESSAGEDATE d FROM ZWAMESSAGE m"
        " JOIN ZWACHATSESSION c ON c.Z_PK = m.ZCHATSESSION"
        f" WHERE c.ZCONTACTJID IN ({marks}) AND m.Z_PK > ? AND m.ZMESSAGEDATE >= ?",
        (*jids, after_pk, _core(since)),
    ).fetchall()
    return {(r["jid"], _to_dt(r["d"], tz).date()) for r in rows}


def _push_names(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["ZJID"]: r["ZPUSHNAME"]
            for r in conn.execute("SELECT ZJID, ZPUSHNAME FROM ZWAPROFILEPUSHNAME")
            if r["ZJID"] and r["ZPUSHNAME"]}


def _sender(r: sqlite3.Row, push: dict[str, str]) -> str:
    if r["me"]:
        return "Me"
    if r["st"] == 0:
        return r["partner"] or _jid_label(r["chat_jid"])
    jid = r["gm_jid"] or r["from_jid"]
    return (r["gm_name"] or r["gm_first"] or push.get(jid or "") or r["push"]
            or _jid_label(jid))


def messages_for_day(conn: sqlite3.Connection, jid: str, day: date, *, tz: tzinfo,
                     media_root: Path) -> list[Message]:
    start, end = _day_bounds(day, tz)
    push = _push_names(conn)
    rows = conn.execute(
        "SELECT m.Z_PK pk, m.ZSTANZAID stanza, m.ZMESSAGEDATE d, m.ZISFROMME me,"
        " m.ZMESSAGETYPE t, m.ZTEXT text, m.ZFROMJID from_jid, m.ZPUSHNAME push,"
        " mi.ZTITLE caption, mi.ZMEDIALOCALPATH path,"
        " gm.ZCONTACTNAME gm_name, gm.ZFIRSTNAME gm_first, gm.ZMEMBERJID gm_jid,"
        " c.ZPARTNERNAME partner, c.ZSESSIONTYPE st, c.ZCONTACTJID chat_jid"
        " FROM ZWAMESSAGE m JOIN ZWACHATSESSION c ON c.Z_PK = m.ZCHATSESSION"
        " LEFT JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM"
        " LEFT JOIN ZWAGROUPMEMBER gm ON gm.Z_PK = m.ZGROUPMEMBER"
        " WHERE c.ZCONTACTJID = ? AND m.ZMESSAGEDATE >= ? AND m.ZMESSAGEDATE < ?"
        " ORDER BY m.ZMESSAGEDATE, m.Z_PK",
        (jid, start, end),
    ).fetchall()
    return [
        Message(pk=r["pk"], stanza_id=r["stanza"] or f"pk{r['pk']}", at=_to_dt(r["d"], tz),
                sender=_sender(r, push), is_from_me=bool(r["me"]), type_code=r["t"] or 0,
                text=r["text"], caption=r["caption"],
                media_path=(media_root / r["path"]) if r["path"] else None)
        for r in rows
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_whatsapp_store.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/connectors/whatsapp/__init__.py ghostbrain/connectors/whatsapp/store.py tests/whatsapp_fixtures.py tests/test_whatsapp_store.py
git commit -m "feat(whatsapp): read-only ChatStorage reader with schema guard"
```

---

### Task 2: Day renderer

**Files:**
- Create: `ghostbrain/connectors/whatsapp/render.py`
- Test: `tests/test_whatsapp_render.py`

**Interfaces:**
- Consumes: `store.Message` (Task 1).
- Produces:
  - `render.VoiceLine = Callable[[Message], tuple[str, bool]]`, which returns `(body, pending)`.
  - `render.RenderedDay(body:str, lines:int, voice_notes:int, pending:bool, participants:list[str])`
  - `render.render_day(messages:list[Message], voice:VoiceLine) -> RenderedDay`

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ghostbrain.connectors.whatsapp.render import render_day
from ghostbrain.connectors.whatsapp.store import Message

TZ = ZoneInfo("Africa/Johannesburg")


def msg(pk, t, *, text=None, caption=None, sender="Alex", me=False, hh=9, mm=0, path=None):
    return Message(pk=pk, stanza_id=f"S{pk}", at=datetime(2026, 10, 9, hh, mm, tzinfo=TZ),
                   sender="Me" if me else sender, is_from_me=me, type_code=t, text=text,
                   caption=caption, media_path=path)


def no_voice(m):
    raise AssertionError("voice not expected")


def test_type_mapping():
    msgs = [
        msg(1, 0, text="hello"),
        msg(2, 1), msg(3, 1, caption="sunset"),
        msg(4, 2), msg(5, 2, caption="clip"),
        msg(6, 4), msg(7, 5),
        msg(8, 7, text="look https://example.com"),
        msg(9, 8, text="report.pdf"), msg(10, 8),
        msg(11, 11),
        msg(12, 14), msg(13, 15), msg(14, 59), msg(15, 66), msg(16, 10, text="x joined"),
        msg(17, 0, text="   "),
    ]
    out = render_day(msgs, no_voice)
    assert out.body.splitlines() == [
        "**09:00 Alex:** hello",
        "**09:00 Alex:** [image]",
        "**09:00 Alex:** [image: sunset]",
        "**09:00 Alex:** [video]",
        "**09:00 Alex:** [video: clip]",
        "**09:00 Alex:** [contact card]",
        "**09:00 Alex:** [location]",
        "**09:00 Alex:** look https://example.com",
        "**09:00 Alex:** [document: report.pdf]",
        "**09:00 Alex:** [document]",
        "**09:00 Alex:** [gif]",
    ]
    assert out.lines == 11


def test_multiline_text_is_indented():
    out = render_day([msg(1, 0, text="line one\nline two")], no_voice)
    assert out.body == "**09:00 Alex:** line one\n  line two"


def test_voice_lines_and_pending_flag():
    calls = []

    def voice(m):
        calls.append(m.pk)
        return ("🎙 hi there", False) if m.pk == 1 else ("[voice note — transcription pending]", True)

    out = render_day([msg(1, 3, me=True, mm=5), msg(2, 3, mm=6)], voice)
    assert calls == [1, 2]
    assert out.body.splitlines() == [
        "**09:05 Me:** 🎙 hi there",
        "**09:06 Alex:** [voice note — transcription pending]",
    ]
    assert out.voice_notes == 2 and out.pending is True


def test_participants_sorted_unique_and_empty_day():
    out = render_day([msg(1, 0, text="a", sender="Zed"), msg(2, 0, text="b", me=True),
                      msg(3, 0, text="c", sender="Zed")], no_voice)
    assert out.participants == ["Me", "Zed"]
    empty = render_day([msg(1, 15)], no_voice)
    assert empty.lines == 0 and empty.body == "" and empty.participants == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_whatsapp_render.py -q`
Expected: FAIL with `ModuleNotFoundError: ...whatsapp.render`

- [ ] **Step 3: Implement** `ghostbrain/connectors/whatsapp/render.py`:

```python
"""Render one chat-day of WhatsApp messages as a markdown transcript.

Type codes were settled against the real store on 2026-10-09 (see spec);
anything not listed here is dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ghostbrain.connectors.whatsapp.store import Message

VoiceLine = Callable[[Message], tuple[str, bool]]

TEXT, IMAGE, VIDEO, VOICE, CONTACT, LOCATION, LINK, DOCUMENT, GIF = 0, 1, 2, 3, 4, 5, 7, 8, 11


@dataclass
class RenderedDay:
    body: str = ""
    lines: int = 0
    voice_notes: int = 0
    pending: bool = False
    participants: list[str] = field(default_factory=list)


def _labelled(label: str, detail: str | None) -> str:
    detail = (detail or "").strip()
    return f"[{label}: {detail}]" if detail else f"[{label}]"


def _content(m: Message) -> str | None:
    t = m.type_code
    if t in (TEXT, LINK):
        return (m.text or "").strip() or None
    if t == IMAGE:
        return _labelled("image", m.caption)
    if t == VIDEO:
        return _labelled("video", m.caption)
    if t == CONTACT:
        return "[contact card]"
    if t == LOCATION:
        return "[location]"
    if t == DOCUMENT:
        return _labelled("document", m.text)
    if t == GIF:
        return "[gif]"
    return None


def render_day(messages: list[Message], voice: VoiceLine) -> RenderedDay:
    out = RenderedDay()
    blocks: list[str] = []
    senders: set[str] = set()
    for m in messages:
        if m.type_code == VOICE:
            content, pending = voice(m)
            out.voice_notes += 1
            out.pending = out.pending or pending
        else:
            content = _content(m)
        if not content:
            continue
        head, *rest = content.split("\n")
        blocks.append("\n".join([f"**{m.at:%H:%M} {m.sender}:** {head}",
                                 *(f"  {r}" for r in rest)]))
        senders.add(m.sender)
    out.body = "\n".join(blocks)
    out.lines = len(blocks)
    out.participants = sorted(senders)
    return out
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/test_whatsapp_render.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/whatsapp/render.py tests/test_whatsapp_render.py
git commit -m "feat(whatsapp): render a chat-day as a markdown transcript"
```

---

### Task 3: Voice-note transcription

**Files:**
- Create: `ghostbrain/connectors/whatsapp/voice.py`
- Test: `tests/test_whatsapp_voice.py`

**Interfaces:**
- Consumes: `store.Message` (Task 1), and `ghostbrain.recorder.transcribe.transcribe(wav_path:Path, *, timeout_s:int) -> Path`, which writes a `.txt` next to the WAV and returns its path.
- Produces:
  - `voice.VoiceTranscriber(cache_dir:Path, *, budget:int, transcribe=None, to_wav=None, recording_live=None)`, with `.line_for(msg) -> tuple[str, bool]`. It matches the `render.VoiceLine` type.
  - Constants: `voice.NOT_DOWNLOADED`, `voice.PENDING`, `voice.FAILED`, `voice.MAX_ATTEMPTS = 3`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ghostbrain.connectors.whatsapp import voice as v
from ghostbrain.connectors.whatsapp.store import Message


def vmsg(tmp_path: Path, *, stanza="ABC/1", exists=True) -> Message:
    path = tmp_path / "Message" / "Media" / f"{stanza.replace('/', '_')}.opus"
    if exists:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"opus")
    return Message(pk=1, stanza_id=stanza, at=datetime(2026, 10, 9, tzinfo=timezone.utc),
                   sender="Alex", is_from_me=False, type_code=3, text=None, caption=None,
                   media_path=path)


def fake_to_wav(src: Path, dst: Path) -> None:
    dst.write_bytes(b"wav")


def fake_transcribe(text="hello there"):
    calls = []

    def run(wav: Path, *, timeout_s: int) -> Path:
        calls.append(wav)
        out = wav.with_suffix(".txt")
        out.write_text(f"{text}\n", encoding="utf-8")
        return out

    run.calls = calls
    return run


def make(tmp_path, *, budget=5, transcribe=None, live=False):
    return v.VoiceTranscriber(tmp_path / "cache", budget=budget,
                              transcribe=transcribe or fake_transcribe(),
                              to_wav=fake_to_wav, recording_live=lambda: live)


def test_miss_transcribes_and_caches(tmp_path):
    tr = fake_transcribe()
    t = make(tmp_path, transcribe=tr)
    assert t.line_for(vmsg(tmp_path)) == ("🎙 hello there", False)
    t2 = make(tmp_path, transcribe=fake_transcribe("WRONG"))
    assert t2.line_for(vmsg(tmp_path)) == ("🎙 hello there", False)
    assert len(tr.calls) == 1


def test_not_downloaded_is_not_cached(tmp_path):
    t = make(tmp_path)
    m = vmsg(tmp_path, exists=False)
    assert t.line_for(m) == (v.NOT_DOWNLOADED, False)
    cache = tmp_path / "cache"
    assert not cache.exists() or not any(cache.iterdir())
    m.media_path.parent.mkdir(parents=True, exist_ok=True)
    m.media_path.write_bytes(b"opus")
    assert t.line_for(m) == ("🎙 hello there", False)


def test_budget_exhaustion_is_pending(tmp_path):
    t = make(tmp_path, budget=1)
    assert t.line_for(vmsg(tmp_path, stanza="A"))[1] is False
    assert t.line_for(vmsg(tmp_path, stanza="B")) == (v.PENDING, True)


def test_live_recording_defers(tmp_path):
    tr = fake_transcribe()
    t = make(tmp_path, transcribe=tr, live=True)
    assert t.line_for(vmsg(tmp_path)) == (v.PENDING, True)
    assert tr.calls == []


def test_failures_retry_then_mark_failed(tmp_path):
    def boom(wav, *, timeout_s):
        raise RuntimeError("whisper died")

    m = vmsg(tmp_path)
    for _ in range(v.MAX_ATTEMPTS - 1):
        assert make(tmp_path, transcribe=boom).line_for(m) == (v.PENDING, True)
    assert make(tmp_path, transcribe=boom).line_for(m) == (v.FAILED, False)
    assert make(tmp_path).line_for(m) == (v.FAILED, False)


def test_empty_transcript(tmp_path):
    t = make(tmp_path, transcribe=fake_transcribe(""))
    assert t.line_for(vmsg(tmp_path)) == ("🎙 (no speech)", False)


def test_ffmpeg_missing_is_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "_ffmpeg_binary", lambda: None)
    t = v.VoiceTranscriber(tmp_path / "cache", budget=5, transcribe=fake_transcribe(),
                           recording_live=lambda: False)
    assert t.line_for(vmsg(tmp_path)) == (v.PENDING, True)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_whatsapp_voice.py -q`
Expected: FAIL with `ModuleNotFoundError: ...whatsapp.voice`

- [ ] **Step 3: Implement** `ghostbrain/connectors/whatsapp/voice.py`:

```python
"""Voice-note transcripts via the local whisper pipeline, cached per stanza id.

WhatsApp stores voice notes as .opus; whisper wants 16 kHz mono WAV, so each
note goes through ffmpeg first. Transcripts are cached so rebuilding a day
never re-transcribes; failures retry on later runs up to MAX_ATTEMPTS.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from ghostbrain.connectors.whatsapp.store import Message

log = logging.getLogger("ghostbrain.connectors.whatsapp.voice")

NOT_DOWNLOADED = "[voice note — not downloaded]"
PENDING = "[voice note — transcription pending]"
FAILED = "[voice note — transcription failed]"
MAX_ATTEMPTS = 3
TRANSCRIBE_TIMEOUT_S = 300


def _ffmpeg_binary() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    # The packaged sidecar's PATH often lacks Homebrew.
    for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if Path(p).exists():
            return p
    return None


def _ffmpeg_to_wav(src: Path, dst: Path) -> None:
    binary = _ffmpeg_binary()
    if binary is None:
        raise FileNotFoundError("ffmpeg not found")
    subprocess.run(
        [binary, "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        check=True, timeout=120, capture_output=True,
    )


def _whisper(wav: Path, *, timeout_s: int) -> Path:
    from ghostbrain.recorder.transcribe import transcribe

    return transcribe(wav, timeout_s=timeout_s)


def _recording_live() -> bool:
    from ghostbrain.recorder import live

    return live.current() is not None


def _key(stanza_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stanza_id)


def _voice(text: str) -> str:
    return f"🎙 {text}" if text else "🎙 (no speech)"


class VoiceTranscriber:
    def __init__(self, cache_dir: Path, *, budget: int,
                 transcribe: Callable[..., Path] | None = None,
                 to_wav: Callable[[Path, Path], None] | None = None,
                 recording_live: Callable[[], bool] | None = None) -> None:
        self.cache_dir = cache_dir
        self.budget = budget
        self._transcribe = transcribe or _whisper
        self._to_wav = to_wav or _ffmpeg_to_wav
        self._recording_live = recording_live or _recording_live

    def line_for(self, msg: Message) -> tuple[str, bool]:
        if msg.media_path is None or not msg.media_path.exists():
            return NOT_DOWNLOADED, False
        key = _key(msg.stanza_id)
        cached = self.cache_dir / f"{key}.txt"
        if cached.exists():
            return _voice(cached.read_text(encoding="utf-8").strip()), False
        failed = self.cache_dir / f"{key}.failed"
        attempts = int(failed.read_text() or 0) if failed.exists() else 0
        if attempts >= MAX_ATTEMPTS:
            return FAILED, False
        # Never compete with a live meeting recording for whisper/CPU.
        if self.budget <= 0 or self._recording_live():
            return PENDING, True
        self.budget -= 1
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            text = self._run(msg.media_path)
        except Exception as e:  # noqa: BLE001 — a voice note must never block the day note
            attempts += 1
            log.warning("voice transcription failed (attempt %d) for %s: %s", attempts, key, e)
            failed.write_text(str(attempts))
            return (FAILED, False) if attempts >= MAX_ATTEMPTS else (PENDING, True)
        cached.write_text(text, encoding="utf-8")
        failed.unlink(missing_ok=True)
        return _voice(text), False

    def _run(self, src: Path) -> str:
        with tempfile.TemporaryDirectory(prefix="gb-wa-voice-") as d:
            wav = Path(d) / "voice.wav"
            self._to_wav(src, wav)
            txt = self._transcribe(wav, timeout_s=TRANSCRIBE_TIMEOUT_S)
            return txt.read_text(encoding="utf-8").strip()
```

`test_ffmpeg_missing_is_pending` works because the default `to_wav` raises `FileNotFoundError`. That counts as attempt 1, so the result is `PENDING`.

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/test_whatsapp_voice.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/whatsapp/voice.py tests/test_whatsapp_voice.py
git commit -m "feat(whatsapp): cached whisper transcripts for voice notes"
```

---

### Task 4: Allowlist storage

**Files:**
- Create: `ghostbrain/connectors/whatsapp/allowlist.py`
- Test: `tests/test_whatsapp_allowlist.py`

**Interfaces:**
- Produces:
  - `allowlist.FILENAME = "whatsapp.allowed_chats.json"`
  - `allowlist.load(state_dir:Path) -> dict[str, dict]`, mapping jid to `{"name": str, "context": str|None}`
  - `allowlist.save(state_dir:Path, chats:dict[str, dict]) -> None`, an atomic write

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

import json

from ghostbrain.connectors.whatsapp import allowlist


def test_missing_file_is_empty(tmp_path):
    assert allowlist.load(tmp_path) == {}


def test_round_trip_and_atomic(tmp_path):
    chats = {"1@s.whatsapp.net": {"name": "Alex", "context": None},
             "2@g.us": {"name": "Club", "context": "work"}}
    allowlist.save(tmp_path, chats)
    assert allowlist.load(tmp_path) == chats
    assert json.loads((tmp_path / allowlist.FILENAME).read_text())["chats"] == chats
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_file_is_empty(tmp_path):
    (tmp_path / allowlist.FILENAME).write_text("{not json")
    assert allowlist.load(tmp_path) == {}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_whatsapp_allowlist.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement** `ghostbrain/connectors/whatsapp/allowlist.py`:

```python
"""Opt-in chat allowlist: state/whatsapp.allowed_chats.json."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.whatsapp.allowlist")

FILENAME = "whatsapp.allowed_chats.json"


def load(state_dir: Path) -> dict[str, dict]:
    f = state_dir / FILENAME
    if not f.exists():
        return {}
    try:
        return dict(json.loads(f.read_text(encoding="utf-8")).get("chats") or {})
    except (ValueError, AttributeError):
        log.warning("ignoring unreadable %s", f)
        return {}


def save(state_dir: Path, chats: dict[str, dict]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    f = state_dir / FILENAME
    tmp = f.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"chats": chats}, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, f)
```

The test's glob is `*.tmp`, and `whatsapp.allowed_chats.json.tmp` matches it, so a leftover temp file would be caught.

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/test_whatsapp_allowlist.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/whatsapp/allowlist.py tests/test_whatsapp_allowlist.py
git commit -m "feat(whatsapp): opt-in chat allowlist state file"
```

---

### Task 5: Connector, runner, CLI and scheduler job

**Files:**
- Create: `ghostbrain/connectors/whatsapp/connector.py`
- Create: `ghostbrain/connectors/whatsapp/runner.py`
- Create: `ghostbrain/connectors/whatsapp/__main__.py`
- Modify: `ghostbrain/connectors/whatsapp/__init__.py` (export `WhatsAppConnector`)
- Modify: `ghostbrain/scheduler_jobs.py` (the import block near line 27, and `register_connectors` near line 252)
- Test: `tests/test_whatsapp_connector.py`

**Interfaces:**
- Consumes: Tasks 1–4.
- Produces:
  - `WhatsAppConnector(config:dict, queue_dir:Path, state_dir:Path, *, tz=None, now=None, voice=None)`, with `name = "whatsapp"`, `.run() -> int`, `.health_check() -> bool`, `.fetch(since) -> list[dict]` and `.normalize(raw) -> dict`.
  - The cursor file is `state/whatsapp.cursor.json`: `{"max_pk": int, "chats": {jid: {"first_synced_at": iso}}, "pending_days": [[jid, "YYYY-MM-DD"], ...]}`.
  - Event: `id="whatsapp:day:<jid>:<YYYY-MM-DD>"`, `source="whatsapp"`, `type="chat_day"`, `title="<chat name> — <YYYY-MM-DD>"`. `metadata` keys: `chatJid`, `chatName`, `chatKind`, `day`, `participants`, `messageCount`, `voiceNotes`, `context`.
  - `runner.run() -> RunResult`, and `runner._build(routing, queue_dir, state_dir) -> WhatsAppConnector | None`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_whatsapp_connector.py -q`
Expected: FAIL with `ModuleNotFoundError: ...whatsapp.connector`

- [ ] **Step 3: Implement** `ghostbrain/connectors/whatsapp/connector.py`:

```python
"""WhatsApp connector — one event per allowed chat per local day.

Each run finds chat-days with messages newer than the cursor (or, for a newly
allowed chat, every day in the lookback window) and emits the *whole* day's
transcript, so the worker can overwrite the day note in place.
"""
from __future__ import annotations

import json
import logging
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

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
        self._now = now or (lambda: datetime.now(timezone.utc))
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
        "timestamp": msgs[-1].at.astimezone(timezone.utc).isoformat(),
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
```

Update `ghostbrain/connectors/whatsapp/__init__.py`:

```python
"""WhatsApp connector — see docs/superpowers/specs/2026-10-09-whatsapp-connector-design.md."""
from ghostbrain.connectors.whatsapp.connector import WhatsAppConnector

__all__ = ["WhatsAppConnector"]
```

`ghostbrain/connectors/whatsapp/runner.py`:

```python
"""In-process runner for the WhatsApp connector (macOS only)."""
from __future__ import annotations

import sys
from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.whatsapp import WhatsAppConnector, store


def _build(routing: dict, queue_dir: Path, state_dir: Path) -> WhatsAppConnector | None:
    if sys.platform != "darwin":
        return None
    path = store.default_store_path()
    if not path.exists():
        return None
    cfg = dict(routing.get("whatsapp") or {})
    cfg["store_path"] = str(path)
    return WhatsAppConnector(config=cfg, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("whatsapp", build=_build)
```

`ghostbrain/connectors/whatsapp/__main__.py`:

```python
"""CLI: `python -m ghostbrain.connectors.whatsapp` — one run, prints the result."""
from __future__ import annotations

import logging
from dataclasses import asdict

from ghostbrain.connectors.whatsapp import runner


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    result = runner.run()
    print(asdict(result))
    raise SystemExit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
```

In `ghostbrain/scheduler_jobs.py`, add the import after the `teams_meetings` runner import:

```python
from ghostbrain.connectors.whatsapp import runner as whatsapp_runner
```

and in `register_connectors`, after the `teams_meetings` line:

```python
    scheduler.add_job("whatsapp", Interval(seconds=3600), whatsapp_runner.run, "every 1h")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/test_whatsapp_connector.py tests/test_whatsapp_store.py -q`
Expected: all PASS. Then run `GHOSTBRAIN_STATE_DIR=$(mktemp -d) .venv/bin/pytest tests -q -k "scheduler"`. Expected: PASS, with no job-registry count assertions broken. If a test asserts the exact job list, add `"whatsapp"` to it.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/whatsapp ghostbrain/scheduler_jobs.py tests/test_whatsapp_connector.py
git commit -m "feat(whatsapp): connector emits one event per chat-day; hourly scheduler job"
```

---

### Task 6: Routing rule and note filename and frontmatter

**Files:**
- Modify: `ghostbrain/worker/router.py` (`_fast_route`: add a branch just before the final `return _account_route(event)`, near line 233)
- Modify: `ghostbrain/worker/note_generator.py` (`_build_frontmatter` source branches near line 126; `_filename_for` near line 162)
- Test: `tests/test_whatsapp_routing_notes.py`

**Interfaces:**
- Consumes: the event shape from Task 5.
- Produces:
  - Routing: `RoutingDecision(method="path")` for `source == "whatsapp"`.
  - Filename: `<YYYY-MM-DD>-<slug(chatName)[:40] or "chat">-<last 12 digits of JID>.md`.

- [ ] **Step 1: Write the failing test**

```python
from __future__ import annotations

from pathlib import Path

from ghostbrain.worker import note_generator, router


def ev(name="Alex Example", jid="27820000001@s.whatsapp.net", ctx=None, day="2026-10-09"):
    return {
        "id": f"whatsapp:day:{jid}:{day}", "source": "whatsapp", "type": "chat_day",
        "timestamp": f"{day}T08:00:00+00:00", "title": f"{name} — {day}", "body": "x",
        "metadata": {"chatJid": jid, "chatName": name, "chatKind": "direct", "day": day,
                     "participants": ["Alex Example", "Me"], "messageCount": 3,
                     "voiceNotes": 1, "context": ctx},
    }


def _contexts(vault: Path, *names: str) -> None:
    f = vault / "90-meta" / "routing.yaml"
    f.write_text("contexts:\n" + "".join(f"  - {n}\n" for n in names), encoding="utf-8")


def test_override_then_default_then_personal(vault: Path):
    _contexts(vault, "personal", "work")
    assert router._fast_route(ev(ctx="work"), {}).context == "work"
    d = router._fast_route(ev(), {"whatsapp": {"default_context": "work"}})
    assert d.context == "work" and d.method == "path"
    assert router._fast_route(ev(), {}).context == "personal"


def test_unknown_contexts_fall_back_to_first_configured(vault: Path):
    _contexts(vault, "home", "work")
    assert router._fast_route(ev(ctx="gone"), {}).context == "home"


def test_filename_stable_across_rebuilds_and_unique_per_jid():
    a1 = note_generator._filename_for(ev(), "whatsapp:day:x")
    a2 = note_generator._filename_for({**ev(), "timestamp": "2026-10-09T22:00:00+00:00"}, "id")
    assert a1 == a2 == "2026-10-09-alex-example-27820000001.md"
    g1 = note_generator._filename_for(ev("Club", "120363000000000001@g.us"), "i")
    g2 = note_generator._filename_for(ev("Club", "120363999900000001@g.us"), "i")
    assert g1 != g2
    assert note_generator._filename_for(ev("😀😀"), "i").startswith("2026-10-09-chat-")


def test_frontmatter_keys():
    from ghostbrain.worker.router import RoutingDecision
    front = note_generator._build_frontmatter(
        ev(), RoutingDecision("personal", 1.0, "r", "path"), note_id="whatsapp:day:x")
    for key in ("chatJid", "chatName", "chatKind", "day", "participants", "messageCount",
                "voiceNotes"):
        assert key in front
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_whatsapp_routing_notes.py -q`
Expected: FAIL. The routing tests fall through to `_account_route` or the LLM and return a non-`path` decision, and the filename test gets a timestamped name.

- [ ] **Step 3: Implement.** In `ghostbrain/worker/router.py`, add this just before the final `return _account_route(event)` in `_fast_route`:

```python
    if source == "whatsapp":
        configured = routing_config.contexts()
        candidates = (metadata.get("context"),
                      (routing.get("whatsapp") or {}).get("default_context"),
                      "personal")
        ctx = next((c for c in candidates if c and c in configured), configured[0])
        log.info("path-routed event=%s ctx=%s whatsapp", event.get("id"), ctx)
        return RoutingDecision(
            context=ctx,
            confidence=1.0,
            reasoning="whatsapp chat context (override → default_context → personal)",
            method="path",
        )
```

In `ghostbrain/worker/note_generator.py` `_build_frontmatter`, add after the `gdrive` branch:

```python
    elif source == "whatsapp":
        for key in ("chatJid", "chatName", "chatKind", "day", "participants",
                    "messageCount", "voiceNotes"):
            if md.get(key) is not None:
                front[key] = md[key]
```

In `_filename_for`, add after the `gdrive` block:

```python
    if event.get("source") == "whatsapp":
        # One note per chat per day, overwritten on every rebuild. The JID's
        # last 12 digits keep it unique — group JIDs share a long prefix.
        md = event.get("metadata") or {}
        digits = re.sub(r"\D", "", md.get("chatJid") or "")[-12:] or "0"
        name_slug = _slugify(md.get("chatName") or "")[:40] or "chat"
        return f"{md.get('day')}-{name_slug}-{digits}.md"
```

- [ ] **Step 4: Run it to verify it passes**

Run: `.venv/bin/pytest tests/test_whatsapp_routing_notes.py tests/test_router.py tests/test_note_generator.py tests/test_no_hardcoded_contexts.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/worker/router.py ghostbrain/worker/note_generator.py tests/test_whatsapp_routing_notes.py
git commit -m "feat(whatsapp): path routing to personal/override; stable per-chat-day note filename"
```

---

### Task 7: Sidecar API, probe, display entry and access provider

**Files:**
- Create: `ghostbrain/api/routes/whatsapp.py`
- Modify: `ghostbrain/api/main.py` (import, and `app.include_router(whatsapp_routes.router)` after `connectors_routes`)
- Modify: `ghostbrain/api/routes/connectors.py:26-29` (`SYNCABLE`: add `"whatsapp"`)
- Modify: `ghostbrain/api/routes/scheduler.py` (its `SYNCABLE` set: add `"whatsapp"`)
- Modify: `ghostbrain/api/repo/connectors.py` (a `_DISPLAY["whatsapp"]` entry)
- Modify: `ghostbrain/api/repo/connector_probe.py` (a `whatsapp` branch in `probe()`)
- Modify: `ghostbrain/api/auth/providers/local_grant.py` (`WhatsAppStoreProvider`)
- Modify: `ghostbrain/api/auth/providers/register_all.py` (register `"whatsapp"`)
- Test: `tests/api/routes/test_whatsapp_routes.py`, `tests/api/repo/test_connector_probe_whatsapp.py`

**Interfaces:**
- Consumes: `store.*` (Task 1) and `allowlist.load/save` (Task 4).
- Produces:
  - `GET /v1/connectors/whatsapp/chats` returns `200 [{jid, name, kind, lastMessageAt, messageCount, allowed, context}]`, or `409 {"detail": str}`.
  - `PUT /v1/connectors/whatsapp/chats` takes body `{"chats": {jid: {"allowed": bool, "context": str|null}}}` and returns the same list as GET.
  - `connector_probe._whatsapp_store_status() -> tuple[str, str|None]`, where the state is `"ok" | "missing" | "denied" | "schema"`.

- [ ] **Step 1: Write the failing tests**

`tests/api/routes/test_whatsapp_routes.py`:

```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.connectors.whatsapp import allowlist
from tests.whatsapp_fixtures import make_store

TZ = ZoneInfo("Africa/Johannesburg")
A = "27820000001@s.whatsapp.net"
G = "120363000000000001@g.us"


@pytest.fixture
def client(vault: Path, tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    b = make_store(tmp_path / "ChatStorage.sqlite")
    b.chat(1, A, "Alex", kind=0, last=datetime(2026, 10, 8, 9, tzinfo=TZ))
    b.chat(2, G, "Club", kind=1, last=datetime(2026, 10, 9, 9, tzinfo=TZ))
    b.message(10, 1, datetime(2026, 10, 8, 9, tzinfo=TZ), text="x")
    monkeypatch.setenv("GHOSTBRAIN_WHATSAPP_STORE", str(b.close()))
    app = create_app(token="test-token-1234567890")
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-token-1234567890"})
    return c


def test_get_lists_chats_merged_with_allowlist(client, tmp_path):
    allowlist.save(tmp_path / "state", {A: {"name": "Alex", "context": "work"}})
    r = client.get("/v1/connectors/whatsapp/chats")
    assert r.status_code == 200
    body = r.json()
    assert [c["jid"] for c in body] == [G, A]
    alex = body[1]
    assert alex == {"jid": A, "name": "Alex", "kind": "direct",
                    "lastMessageAt": alex["lastMessageAt"], "messageCount": 1,
                    "allowed": True, "context": "work"}
    assert body[0]["allowed"] is False and body[0]["context"] is None


def test_put_round_trip(client, tmp_path):
    r = client.put("/v1/connectors/whatsapp/chats",
                   json={"chats": {G: {"allowed": True, "context": None},
                                   A: {"allowed": False, "context": None}}})
    assert r.status_code == 200
    assert allowlist.load(tmp_path / "state") == {G: {"name": "Club", "context": None}}
    assert [c["allowed"] for c in r.json()] == [True, False]


def test_put_ignores_unknown_jids(client, tmp_path):
    client.put("/v1/connectors/whatsapp/chats",
               json={"chats": {"999@s.whatsapp.net": {"allowed": True, "context": None}}})
    assert allowlist.load(tmp_path / "state") == {}


def test_missing_store_is_409(client, monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_WHATSAPP_STORE", str(tmp_path / "nope.sqlite"))
    r = client.get("/v1/connectors/whatsapp/chats")
    assert r.status_code == 409
    assert "WhatsApp" in r.json()["detail"]


def test_whatsapp_is_listed_and_syncable(client):
    ids = [c["id"] for c in client.get("/v1/connectors").json()]
    assert "whatsapp" in ids
```

`tests/api/repo/test_connector_probe_whatsapp.py`:

```python
from __future__ import annotations

from ghostbrain.api.repo import connector_probe as cp


def test_off_when_not_macos(monkeypatch):
    monkeypatch.setattr(cp, "_platform", lambda: "linux")
    assert cp.probe("whatsapp").state == "off"


def test_off_when_store_missing(monkeypatch):
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("missing", None))
    assert cp.probe("whatsapp").state == "off"


def test_err_when_denied_or_schema(monkeypatch):
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("denied", "no access"))
    r = cp.probe("whatsapp")
    assert r.state == "err" and "Full Disk Access" in r.error
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("schema", "missing X"))
    assert cp.probe("whatsapp").state == "err"


def test_on_only_with_selected_chats(monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("ok", None))
    assert cp.probe("whatsapp").state == "off"
    from ghostbrain.connectors.whatsapp import allowlist
    allowlist.save(tmp_path, {"1@s.whatsapp.net": {"name": "A", "context": None}})
    r = cp.probe("whatsapp")
    assert r.state == "on" and r.account == "1 chat"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/api/routes/test_whatsapp_routes.py tests/api/repo/test_connector_probe_whatsapp.py -q`
Expected: FAIL with 404 on the routes and `probe("whatsapp").state == "off"` mismatches.

- [ ] **Step 3: Implement.** Create `ghostbrain/api/routes/whatsapp.py`:

```python
"""GET/PUT /v1/connectors/whatsapp/chats — the opt-in chat picker's backend."""
from __future__ import annotations

import sqlite3
from contextlib import closing

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from ghostbrain.connectors.whatsapp import allowlist, store
from ghostbrain.paths import state_dir

router = APIRouter(prefix="/v1/connectors/whatsapp", tags=["connectors"])

ACCESS_HINT = ("Poltergeist can't read WhatsApp's data. Grant it Full Disk Access in "
               "System Settings → Privacy & Security → Full Disk Access, then retry.")


class ChatChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowed: bool
    context: str | None = None


class ChatsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chats: dict[str, ChatChoice]


def _chats() -> list[store.Chat]:
    path = store.default_store_path()
    try:
        with closing(store.open_store(path)) as conn:
            store.check_schema(conn)
            return store.list_chats(conn, tz=store.local_tz())
    except FileNotFoundError as e:
        raise HTTPException(status_code=409,
                            detail="WhatsApp for Mac isn't installed or signed in.") from e
    except store.StoreSchemaError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except (PermissionError, sqlite3.OperationalError) as e:
        raise HTTPException(status_code=409, detail=ACCESS_HINT) from e


def _merged(chats: list[store.Chat]) -> list[dict]:
    allowed = allowlist.load(state_dir())
    return [
        {"jid": c.jid, "name": c.name, "kind": c.kind,
         "lastMessageAt": c.last_message_at.isoformat() if c.last_message_at else None,
         "messageCount": c.message_count, "allowed": c.jid in allowed,
         "context": (allowed.get(c.jid) or {}).get("context")}
        for c in chats
    ]


@router.get("/chats")
def list_whatsapp_chats() -> list[dict]:
    return _merged(_chats())


@router.put("/chats")
def save_whatsapp_chats(body: ChatsBody) -> list[dict]:
    chats = _chats()
    names = {c.jid: c.name for c in chats}
    current = allowlist.load(state_dir())
    for jid, choice in body.chats.items():
        if jid not in names:
            continue
        if choice.allowed:
            current[jid] = {"name": names[jid], "context": choice.context}
        else:
            current.pop(jid, None)
    allowlist.save(state_dir(), current)
    return _merged(chats)
```

In `ghostbrain/api/main.py`, add `from ghostbrain.api.routes import whatsapp as whatsapp_routes` to the route imports (alphabetical, after `vault`), and add `app.include_router(whatsapp_routes.router)` right after `app.include_router(connectors_routes.router)`.

In `ghostbrain/api/routes/connectors.py`, change `SYNCABLE`:

```python
SYNCABLE = {
    "github", "gmail", "slack", "calendar", "jira", "confluence",
    "outlook_mail", "teams_chat", "teams_meetings", "gdrive", "whatsapp",
}
```

Make the same addition to the `SYNCABLE` set in `ghostbrain/api/routes/scheduler.py`; check it with `grep -n SYNCABLE -A4 ghostbrain/api/routes/scheduler.py`.

In `ghostbrain/api/repo/connectors.py`, add to `_DISPLAY` after `teams_meetings`:

```python
    "whatsapp": {
        "displayName": "WhatsApp",
        "scopes": ["read WhatsApp for Mac's local data"],
        "pulls": ["chats you select", "voice-note transcripts"],
        "vaultDestination": "20-contexts/{ctx}/whatsapp/",
    },
```

In `ghostbrain/api/repo/connector_probe.py`, add these helpers above `probe()`:

```python
def _whatsapp_store_status() -> tuple[str, str | None]:
    import sqlite3
    from contextlib import closing

    from ghostbrain.connectors.whatsapp import store

    try:
        with closing(store.open_store(store.default_store_path())) as conn:
            store.check_schema(conn)
    except FileNotFoundError:
        return "missing", None
    except store.StoreSchemaError as e:
        return "schema", str(e)
    except (PermissionError, sqlite3.OperationalError) as e:
        return "denied", str(e)
    return "ok", None


def _whatsapp_probe() -> ProbeResult:
    if _platform() != "darwin":
        return ProbeResult("off")
    status, detail = _whatsapp_store_status()
    if status == "missing":
        return ProbeResult("off")
    if status == "denied":
        return ProbeResult("err", error="Grant Poltergeist Full Disk Access to read WhatsApp")
    if status == "schema":
        return ProbeResult("err", error=detail)
    from ghostbrain.connectors.whatsapp import allowlist

    n = len(allowlist.load(state_dir()))
    if n == 0:
        return ProbeResult("off")
    return ProbeResult("on", account=f"{n} chat" + ("" if n == 1 else "s"))
```

and in `probe()`, before the final `return ProbeResult("off")`:

```python
    if connector_id == "whatsapp":
        return _whatsapp_probe()
```

`connector_probe` imports `state_dir` at module load. The test sets `GHOSTBRAIN_STATE_DIR`, and `state_dir()` reads the env var on every call, so no reload is needed.

In `ghostbrain/api/auth/providers/local_grant.py`, add at the end:

```python
class WhatsAppStoreProvider:
    """Checks Poltergeist can read WhatsApp for Mac's local store (Full Disk Access)."""

    pattern = "local_grant"

    def _check(self) -> NextAction:
        from ghostbrain.api.repo.connector_probe import _whatsapp_store_status

        status, detail = _whatsapp_store_status()
        if status == "ok":
            return NextAction(kind="done")
        if status == "missing":
            return NextAction(kind="need_grant",
                              message="Install WhatsApp for Mac and sign in, then press Re-check.")
        if status == "schema":
            return NextAction(kind="need_grant",
                              message=f"This WhatsApp version isn't supported yet: {detail}")
        return NextAction(
            kind="need_grant",
            message=("Grant Poltergeist Full Disk Access: System Settings → Privacy & "
                     "Security → Full Disk Access, enable Poltergeist, then press Re-check."),
        )

    def start(self, connector_id, params):
        """Report whether the store is readable; done immediately when it is."""
        return self._check()

    def submit(self, connector_id, session, data):
        """No form input for this flow."""
        return session.next

    def poll(self, connector_id, session):
        """Re-check access after the user changed System Settings."""
        nxt = self._check()
        session.next = nxt
        if nxt.kind == "done":
            session.status = "success"
        else:
            session.status = "error"
            session.error = nxt.message

    def account_label(self, session):
        """Return account label."""
        return "WhatsApp for Mac"
```

In `ghostbrain/api/auth/providers/register_all.py`, extend the import:

```python
from ghostbrain.api.auth.providers.local_grant import (
    ClaudeCodeProvider,
    MacosCalendarProvider,
    WhatsAppStoreProvider,
)
```

and add `registry.register("whatsapp", WhatsAppStoreProvider())` after the `macos_calendar` line.

- [ ] **Step 4: Run them to verify they pass**

Run: `.venv/bin/pytest tests/api/routes/test_whatsapp_routes.py tests/api/repo/test_connector_probe_whatsapp.py tests/api -q`
Expected: all PASS. If `tests/api/repo/test_connectors_registry.py` pins the exact connector-id set, add `"whatsapp"` there.

Then add one more check to `tests/api/repo/test_connector_probe_whatsapp.py`, for the provider's denied message:

```python
def test_provider_denied_message(monkeypatch):
    from ghostbrain.api.auth.providers.local_grant import WhatsAppStoreProvider
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("denied", "x"))
    nxt = WhatsAppStoreProvider().start("whatsapp", {})
    assert nxt.kind == "need_grant" and "Full Disk Access" in nxt.message
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("ok", None))
    assert WhatsAppStoreProvider().start("whatsapp", {}).kind == "done"
```

Run it again and expect PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api tests/api
git commit -m "feat(whatsapp): chat picker API, probe, display entry, Full Disk Access provider"
```

---

### Task 8: Desktop card, hooks and chat picker

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (add `WhatsAppChat`)
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (add `useWhatsAppChats` and `useSaveWhatsAppChats`)
- Modify: `desktop/src/renderer/lib/connector-catalog.ts` (a WhatsApp card)
- Create: `desktop/src/renderer/public/assets/connectors/whatsapp.svg`
- Create: `desktop/src/renderer/components/WhatsAppChatPicker.tsx`
- Modify: `desktop/src/renderer/screens/connectors.tsx` (render the picker in `ConnectorDetailPanel` after the `accounts` block, near line 574)
- Test: `desktop/src/renderer/__tests__/WhatsAppChatPicker.test.tsx`; update `desktop/src/renderer/__tests__/connector-catalog.test.ts`

**Interfaces:**
- Consumes: `GET`/`PUT /v1/connectors/whatsapp/chats` (Task 7).
- Produces:
  - `type WhatsAppChat = { jid: string; name: string; kind: 'direct' | 'group'; lastMessageAt: string | null; messageCount: number; allowed: boolean; context: string | null }`
  - `useWhatsAppChats(enabled?: boolean)`, query key `['whatsapp', 'chats']`
  - `useSaveWhatsAppChats()`, a mutation taking `Record<string, { allowed: boolean; context: string | null }>`
  - `<WhatsAppChatPicker />`

- [ ] **Step 1: Write the failing test** (`desktop/src/renderer/__tests__/WhatsAppChatPicker.test.tsx`)

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { WhatsAppChatPicker } from '../components/WhatsAppChatPicker';
import type { VaultContexts, WhatsAppChat } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});

const chats: WhatsAppChat[] = [
  { jid: 'g1@g.us', name: 'Book Club', kind: 'group', lastMessageAt: '2026-10-09T09:00:00+02:00', messageCount: 40, allowed: false, context: null },
  { jid: 'd1@s.whatsapp.net', name: 'Alex Example', kind: 'direct', lastMessageAt: '2026-10-08T09:00:00+02:00', messageCount: 12, allowed: true, context: 'work' },
];
const contexts: VaultContexts = { contexts: ['personal', 'work'], archived: [] };

function setup() {
  vi.mocked(client.get).mockImplementation(async (path: string) => {
    if (path === '/v1/connectors/whatsapp/chats') return chats;
    if (path === '/v1/vault/contexts') return contexts;
    throw new Error(`unexpected ${path}`);
  });
  vi.mocked(client.put).mockResolvedValue(chats);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WhatsAppChatPicker />
    </QueryClientProvider>,
  );
}

describe('WhatsAppChatPicker', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it('lists chats and filters by search and kind', async () => {
    setup();
    expect(await screen.findByText('Book Club')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('search chats'), { target: { value: 'alex' } });
    expect(screen.queryByText('Book Club')).toBeNull();
    expect(screen.getByText('Alex Example')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('search chats'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'groups' }));
    expect(screen.queryByText('Alex Example')).toBeNull();
  });

  it('saves only changed chats with their context', async () => {
    setup();
    fireEvent.click(await screen.findByLabelText('include Book Club'));
    fireEvent.change(screen.getByLabelText('context for Book Club'), { target: { value: 'work' } });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() => expect(client.put).toHaveBeenCalled());
    expect(client.put).toHaveBeenCalledWith('/v1/connectors/whatsapp/chats', {
      chats: { 'g1@g.us': { allowed: true, context: 'work' } },
    });
  });

  it('shows the access error from the sidecar', async () => {
    vi.mocked(client.get).mockImplementation(async (path: string) => {
      if (path === '/v1/vault/contexts') return contexts;
      throw new client.ApiError(409, 'Grant Full Disk Access');
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><WhatsAppChatPicker /></QueryClientProvider>);
    expect(await screen.findByText(/Full Disk Access/)).toBeTruthy();
  });
});
```

Before writing the test, check the `ApiError` constructor signature with `grep -n "class ApiError" -A8 desktop/src/renderer/lib/api/client.ts`. Adapt `new client.ApiError(409, ...)` to match it. The rendered message must come from the error's detail/message field.

In `desktop/src/renderer/__tests__/connector-catalog.test.ts`, add `'whatsapp'` to the `arrayContaining` list.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/WhatsAppChatPicker.test.tsx src/renderer/__tests__/connector-catalog.test.ts`
Expected: FAIL. The component module doesn't exist yet and the catalog lacks `whatsapp`.

- [ ] **Step 3: Implement.** In `desktop/src/shared/api-types.ts`:

```ts
export interface WhatsAppChat {
  jid: string;
  name: string;
  kind: 'direct' | 'group';
  lastMessageAt: string | null;
  messageCount: number;
  allowed: boolean;
  context: string | null;
}
```

In `desktop/src/renderer/lib/api/hooks.ts`, add `put` to the client import and `WhatsAppChat` to the type import, then add:

```ts
export function useWhatsAppChats(enabled = true) {
  return useQuery({
    queryKey: ['whatsapp', 'chats'],
    queryFn: () => get<WhatsAppChat[]>('/v1/connectors/whatsapp/chats'),
    enabled,
    retry: false,
    staleTime: 60_000,
  });
}

export function useSaveWhatsAppChats() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (chats: Record<string, { allowed: boolean; context: string | null }>) =>
      put<WhatsAppChat[]>('/v1/connectors/whatsapp/chats', { chats }),
    onSuccess: (data) => {
      qc.setQueryData(['whatsapp', 'chats'], data);
      qc.invalidateQueries({ queryKey: ['connectors'] });
      qc.invalidateQueries({ queryKey: ['connector', 'whatsapp'] });
    },
  });
}
```

In `desktop/src/renderer/lib/connector-catalog.ts`, add after the `macos_calendar` card:

```ts
  {
    id: 'whatsapp',
    displayName: 'WhatsApp',
    blurb: 'macOS only. Reads WhatsApp for Mac\'s local data, read-only, for the chats you pick — one note per chat per day, voice notes transcribed locally. Needs Full Disk Access.',
    pattern: 'local_grant',
  },
```

Create `desktop/src/renderer/public/assets/connectors/whatsapp.svg`. It's a neutral, generic speech-bubble glyph, not the WhatsApp logo, to avoid trademark issues:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11.5a8 8 0 0 1-11.8 7L4 20l1.5-4.1A8 8 0 1 1 20 11.5Z"/><path d="M9 9.5c0 3 2.5 5.5 5.5 5.5l1-1.5-2-1-1 .8a4 4 0 0 1-1.8-1.8l.8-1-1-2L9 9.5Z"/></svg>
```

Create `desktop/src/renderer/components/WhatsAppChatPicker.tsx`. Before writing it, read `desktop/src/renderer/components/ConnectorAccounts.tsx` and copy its class names and its `Pill`/button primitives so the picker matches the detail pane's look. The structure and behaviour below are the contract the test relies on:

```tsx
import { useMemo, useState } from 'react';

import { useContexts, useSaveWhatsAppChats, useWhatsAppChats } from '../lib/api/hooks';
import type { WhatsAppChat } from '../../shared/api-types';

type Kind = 'all' | 'direct' | 'group';
type Choice = { allowed: boolean; context: string | null };

export function WhatsAppChatPicker() {
  const chats = useWhatsAppChats();
  const contexts = useContexts();
  const save = useSaveWhatsAppChats();
  const [query, setQuery] = useState('');
  const [kind, setKind] = useState<Kind>('all');
  const [edits, setEdits] = useState<Record<string, Choice>>({});

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (chats.data ?? []).filter(
      (c) => (kind === 'all' || c.kind === kind) && (!q || c.name.toLowerCase().includes(q)),
    );
  }, [chats.data, query, kind]);

  if (chats.isLoading) return <div className="text-[12px] opacity-70">loading chats…</div>;
  if (chats.error) {
    return <div className="text-[12px] text-red-400">{(chats.error as Error).message}</div>;
  }

  const current = (c: WhatsAppChat): Choice =>
    edits[c.jid] ?? { allowed: c.allowed, context: c.context };
  const edit = (c: WhatsAppChat, next: Partial<Choice>) =>
    setEdits((e) => ({ ...e, [c.jid]: { ...current(c), ...next } }));
  const dirty = Object.keys(edits).length > 0;

  return (
    <div className="flex flex-col gap-[8px]">
      <div className="text-[11px] opacity-70">
        Nothing is imported until you tick a chat. A newly ticked chat's first sync pulls the last 90 days.
      </div>
      <div className="flex gap-[6px]">
        <input
          className="flex-1 rounded border border-white/10 bg-transparent px-[8px] py-[4px] text-[12px]"
          placeholder="search chats"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {(['all', 'direct', 'group'] as const).map((k) => (
          <button
            key={k}
            type="button"
            className={`rounded px-[8px] text-[11px] ${kind === k ? 'bg-white/15' : 'opacity-70'}`}
            onClick={() => setKind(k)}
          >
            {k === 'group' ? 'groups' : k}
          </button>
        ))}
      </div>
      <ul className="max-h-[320px] overflow-y-auto">
        {rows.map((c) => {
          const cur = current(c);
          return (
            <li key={c.jid} className="flex items-center gap-[8px] py-[3px] text-[12px]">
              <input
                type="checkbox"
                aria-label={`include ${c.name}`}
                checked={cur.allowed}
                onChange={(e) => edit(c, { allowed: e.target.checked })}
              />
              <span className="flex-1 truncate">{c.name}</span>
              <span className="opacity-60">{c.kind}</span>
              <span className="w-[80px] text-right opacity-60">
                {c.lastMessageAt ? c.lastMessageAt.slice(0, 10) : '—'}
              </span>
              <select
                aria-label={`context for ${c.name}`}
                className="bg-transparent text-[11px]"
                value={cur.context ?? ''}
                disabled={!cur.allowed}
                onChange={(e) => edit(c, { context: e.target.value || null })}
              >
                <option value="">default</option>
                {(contexts.data?.contexts ?? []).map((ctx) => (
                  <option key={ctx} value={ctx}>{ctx}</option>
                ))}
              </select>
            </li>
          );
        })}
      </ul>
      <div>
        <button
          type="button"
          className="rounded bg-white/15 px-[10px] py-[4px] text-[12px] disabled:opacity-40"
          disabled={!dirty || save.isPending}
          onClick={() => save.mutate(edits, { onSuccess: () => setEdits({}) })}
        >
          save
        </button>
      </div>
    </div>
  );
}
```

In `desktop/src/renderer/screens/connectors.tsx`, import `WhatsAppChatPicker` next to the `ConnectorAccounts` import. After the `{accounts !== null && (...)}` block (around line 575), add:

```tsx
        {c.id === 'whatsapp' && (
          <DetailBlock label="chats">
            <WhatsAppChatPicker />
          </DetailBlock>
        )}
```

- [ ] **Step 4: Run them to verify they pass**

Run: `cd desktop && npx vitest run src/renderer/__tests__/WhatsAppChatPicker.test.tsx src/renderer/__tests__/connector-catalog.test.ts && npm run typecheck`
Expected: tests PASS and the type check is clean. Then run `npx vitest run` for the whole desktop suite and expect no new failures.

- [ ] **Step 5: Commit**

```bash
git add desktop/src
git commit -m "feat(whatsapp): connector card and opt-in chat picker in the detail pane"
```

---

### Task 9: Onboarding docs, full verification and live smoke

**Files:**
- Modify: the `onboarding-poltergeist` skill source in this repo. Locate it with `grep -rl "name: onboarding-poltergeist" --include=SKILL.md .`. If it lives outside the repo, skip this step and say so in the final report.
- Modify: `desktop/CHANGELOG.md` only if the repo's release flow expects manual entries. Check with `git log -5 --format=%s -- desktop/CHANGELOG.md`; if those are all release-please commits, don't touch it.

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Add a WhatsApp section to the onboarding skill.** Put it after the macOS Calendar section, matching that section's heading level:

```markdown
### WhatsApp (macOS only)

1. Install WhatsApp for Mac from the App Store and sign in (link it to your phone).
2. In Poltergeist → Connectors → WhatsApp, press Connect. If it asks for access, open
   System Settings → Privacy & Security → Full Disk Access, enable Poltergeist, then Re-check.
3. In the WhatsApp detail pane, tick the chats to import (nothing is imported until you do),
   optionally choose a context per chat (default: personal), and Save.
4. The next hourly run (or "sync now") pulls the last 90 days for newly ticked chats —
   one note per chat per day under `20-contexts/<ctx>/whatsapp/`. Voice notes are
   transcribed locally (needs ffmpeg + a whisper model; up to 40 per run).
```

- [ ] **Step 2: Run the full Python suite with state sandboxed**

Run: `GHOSTBRAIN_STATE_DIR=$(mktemp -d) .venv/bin/pytest -q`
Expected: all PASS. Fix any registry or job-list assertions that pin exact connector sets by adding `whatsapp`.

- [ ] **Step 3: Run lint**

Run: `.venv/bin/ruff check ghostbrain tests` and expect it to be clean. Release builds lint, PR CI does not, so check it here.

- [ ] **Step 4: Live smoke against the real store (read-only, sandboxed vault and state)**

```bash
SMOKE=$(mktemp -d) && export GHOSTBRAIN_STATE_DIR=$SMOKE/state VAULT_PATH=$SMOKE/vault
.venv/bin/python -c "from ghostbrain.bootstrap import bootstrap; from pathlib import Path; import os; bootstrap(Path(os.environ['VAULT_PATH']))"
.venv/bin/python - <<'EOF'
from contextlib import closing
from ghostbrain.connectors.whatsapp import store, allowlist
from ghostbrain.paths import state_dir
with closing(store.open_store(store.default_store_path())) as c:
    store.check_schema(c)
    chats = store.list_chats(c, tz=store.local_tz())
print(len(chats), "chats readable")
allowlist.save(state_dir(), {chats[0].jid: {"name": chats[0].name, "context": None}})
EOF
.venv/bin/python -m ghostbrain.connectors.whatsapp
ls $SMOKE/queue/pending 2>/dev/null | head || ls ~/ghostbrain/queue/pending | grep whatsapp | head
```

Expected:
- the script prints a chat count of roughly 740;
- the CLI prints `ok: True` with `queued > 0`;
- the queue contains `whatsapp` event files.

Don't run the worker against the real vault. Report the counts only. **Don't print message bodies in the report.** Then delete the smoke dir with `rm -rf "$SMOKE"`. The queue location depends on `queue_dir()`; check `grep -n "def queue_dir" -A6 ghostbrain/paths.py` first, and if it isn't under `VAULT_PATH`, set the matching env var so the smoke doesn't write into the real queue.

- [ ] **Step 5: Commit and report**

```bash
git add -A && git commit -m "docs(whatsapp): onboarding section" || true
git log --oneline origin/main..HEAD
```

Report:
- the commit list;
- the test counts (Python and desktop);
- the smoke results (chat count, events queued);
- anything skipped, and why.
