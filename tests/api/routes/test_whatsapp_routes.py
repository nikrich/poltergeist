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


def test_put_rejects_unknown_context(client, tmp_path):
    allowlist.save(tmp_path / "state", {A: {"name": "Alex", "context": None}})
    r = client.put("/v1/connectors/whatsapp/chats",
                   json={"chats": {G: {"allowed": True, "context": "nope"}}})
    assert r.status_code == 422
    assert "nope" in r.json()["detail"]
    assert allowlist.load(tmp_path / "state") == {A: {"name": "Alex", "context": None}}


def test_corrupt_store(client, monkeypatch, tmp_path):
    bad = tmp_path / "garbage.sqlite"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    monkeypatch.setenv("GHOSTBRAIN_WHATSAPP_STORE", str(bad))
    assert client.get("/v1/connectors/whatsapp/chats").status_code == 409
    r = client.get("/v1/connectors")
    assert r.status_code == 200
    assert "whatsapp" in [c["id"] for c in r.json()]


def test_sqlite_auth_is_access_hint(client, monkeypatch):
    import sqlite3

    from ghostbrain.api.routes.whatsapp import ACCESS_HINT
    from ghostbrain.connectors.whatsapp import store

    def deny(path):
        raise sqlite3.DatabaseError("authorization denied")

    monkeypatch.setattr(store, "open_store", deny)
    r = client.get("/v1/connectors/whatsapp/chats")
    assert r.status_code == 409
    assert r.json()["detail"] == ACCESS_HINT
