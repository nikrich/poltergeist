from __future__ import annotations

import sqlite3
from datetime import date, datetime
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


def test_local_tz_resolves_iana_zone_from_symlink(tmp_path):
    target = tmp_path / "usr" / "share" / "zoneinfo" / "America" / "New_York"
    target.parent.mkdir(parents=True)
    target.touch()
    link = tmp_path / "localtime"
    link.symlink_to(target)
    assert store.local_tz(link) == ZoneInfo("America/New_York")


def test_local_tz_falls_back_to_fixed_offset_for_plain_file(tmp_path):
    plain = tmp_path / "localtime"
    plain.touch()
    tz = store.local_tz(plain)
    assert tz is not None
    assert tz.utcoffset(datetime.now()) is not None


def test_dst_day_bucketing_keeps_late_message_on_its_local_day(tmp_path):
    ny = ZoneInfo("America/New_York")
    jid = "15550000001@s.whatsapp.net"
    b = make_store(tmp_path / "ChatStorage.sqlite")
    b.chat(1, jid, "Night Owl", kind=0, last=datetime(2026, 3, 7, 23, 30, tzinfo=ny))
    b.message(200, 1, datetime(2026, 3, 7, 23, 30, tzinfo=ny), text="late, before spring-forward")
    path = b.close()
    c = store.open_store(path)
    try:
        since = datetime(2026, 3, 1, tzinfo=ny)
        assert store.dirty_days(c, [jid], after_pk=0, since=since, tz=ny) == {(jid, date(2026, 3, 7))}
        day_msgs = store.messages_for_day(c, jid, date(2026, 3, 7), tz=ny, media_root=tmp_path)
        assert [m.pk for m in day_msgs] == [200]
        assert day_msgs[0].at == datetime(2026, 3, 7, 23, 30, tzinfo=ny)
        assert store.messages_for_day(c, jid, date(2026, 3, 8), tz=ny, media_root=tmp_path) == []
    finally:
        c.close()
