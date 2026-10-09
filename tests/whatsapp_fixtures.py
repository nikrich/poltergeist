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
