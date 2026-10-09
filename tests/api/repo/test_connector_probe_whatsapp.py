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


def test_provider_denied_message(monkeypatch):
    from ghostbrain.api.auth.providers.local_grant import WhatsAppStoreProvider
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("denied", "x"))
    nxt = WhatsAppStoreProvider().start("whatsapp", {})
    assert nxt.kind == "need_grant" and "Full Disk Access" in nxt.message
    monkeypatch.setattr(cp, "_whatsapp_store_status", lambda: ("ok", None))
    assert WhatsAppStoreProvider().start("whatsapp", {}).kind == "done"
