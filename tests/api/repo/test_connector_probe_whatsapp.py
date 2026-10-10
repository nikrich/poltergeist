from __future__ import annotations

import pytest

from ghostbrain.api.repo import connector_probe as cp
from ghostbrain.connectors.whatsapp import allowlist


@pytest.fixture
def opted_in(monkeypatch, tmp_path):
    """One selected chat, so the probe goes on to check the store."""
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    allowlist.save(tmp_path / "state", {"1@s.whatsapp.net": {"name": "A", "context": None}})


def test_off_when_not_macos(monkeypatch):
    monkeypatch.setattr(cp, "_platform", lambda: "linux")
    assert cp.probe("whatsapp").state == "off"


def test_off_when_store_missing(monkeypatch, opted_in):
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("missing", None))
    assert cp.probe("whatsapp").state == "off"


def test_err_when_denied_or_schema(monkeypatch, opted_in):
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
    allowlist.save(tmp_path, {"1@s.whatsapp.net": {"name": "A", "context": None}})
    r = cp.probe("whatsapp")
    assert r.state == "on" and r.account == "1 chat"


def test_provider_denied_message(monkeypatch):
    from ghostbrain.api.auth.providers.local_grant import WhatsAppStoreProvider
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("denied", "x"))
    nxt = WhatsAppStoreProvider().start("whatsapp", {})
    assert nxt.kind == "need_grant" and "Full Disk Access" in nxt.message
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("ok", None))
    assert WhatsAppStoreProvider().start("whatsapp", {}).kind == "done"


def test_err_when_store_is_corrupt(monkeypatch, tmp_path, opted_in):
    bad = tmp_path / "garbage.sqlite"
    bad.write_bytes(b"this is not a sqlite database" * 100)
    monkeypatch.setenv("GHOSTBRAIN_WHATSAPP_STORE", str(bad))
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    r = cp.probe("whatsapp")
    assert r.state == "err" and "unreadable" in r.error


def test_off_with_empty_allowlist_never_opens_store(monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")

    def must_not_run():
        raise AssertionError("store opened before opt-in")

    monkeypatch.setattr(cp, "_whatsapp_store_status", must_not_run)
    assert cp.probe("whatsapp").state == "off"


def _auth_denied(code: bool):
    import sqlite3

    def raise_auth(path):
        if code:
            e = sqlite3.DatabaseError("not permitted")
            e.sqlite_errorcode = 23  # SQLITE_AUTH
            raise e
        raise sqlite3.DatabaseError("authorization denied")

    return raise_auth


@pytest.mark.parametrize("code", [False, True])
def test_sqlite_auth_is_denied_not_schema(monkeypatch, tmp_path, opted_in, code):
    from ghostbrain.connectors.whatsapp import store
    monkeypatch.setenv("GHOSTBRAIN_WHATSAPP_STORE", str(tmp_path))  # exists
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(store, "open_store", _auth_denied(code))
    assert cp._whatsapp_store_status()[0] == "denied"
    r = cp.probe("whatsapp")
    assert r.state == "err" and "Full Disk Access" in r.error


def test_provider_sqlite_auth_asks_for_full_disk_access(monkeypatch, tmp_path):
    from ghostbrain.api.auth.providers.local_grant import WhatsAppStoreProvider
    from ghostbrain.connectors.whatsapp import store
    monkeypatch.setattr(store, "open_store", _auth_denied(False))
    nxt = WhatsAppStoreProvider().start("whatsapp", {})
    assert nxt.kind == "need_grant" and "Full Disk Access" in nxt.message
