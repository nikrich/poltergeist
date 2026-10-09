"""Read-only access to the macOS WhatsApp store (ChatStorage.sqlite).

All WhatsApp-specific SQL lives here — nothing else in the codebase touches
the schema. The store is Core Data: dates are seconds since 2001-01-01 UTC.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


def local_tz(localtime: Path = Path("/etc/localtime")) -> tzinfo:
    """Resolve the machine's IANA zone (DST-aware) from the /etc/localtime symlink.

    Falls back to the current fixed offset when the link is missing or does not
    point into a zoneinfo database.
    """
    try:
        if localtime.is_symlink():
            target = str(localtime.resolve())
            if "zoneinfo/" in target:
                return ZoneInfo(target.rsplit("zoneinfo/", 1)[1])
    except (ZoneInfoNotFoundError, OSError, ValueError):
        pass
    return datetime.now().astimezone().tzinfo  # type: ignore[return-value]


def open_store(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=1")
    except Exception:
        conn.close()
        raise
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
    return datetime.fromtimestamp(core_seconds + CORE_DATA_EPOCH, tz=UTC).astimezone(tz)


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
