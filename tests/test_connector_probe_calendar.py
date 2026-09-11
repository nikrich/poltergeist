from __future__ import annotations

from ghostbrain.api.repo import connector_probe as cp


def _routing_with_macos(accounts: dict):
    return lambda: {"calendar": {"macos": {"accounts": accounts}}}


def test_eventkit_authorized_with_accounts_is_on(monkeypatch):
    monkeypatch.setattr(cp, "_google_probe", lambda prefix: cp.ProbeResult("off"))
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(cp, "_macos_calendar_authorized", lambda: True)
    monkeypatch.setattr(cp, "_load_routing", _routing_with_macos({"Calendar": "work"}))
    assert cp.probe("calendar").state == "on"


def test_eventkit_authorized_but_no_accounts_stays_off(monkeypatch):
    monkeypatch.setattr(cp, "_google_probe", lambda prefix: cp.ProbeResult("off"))
    monkeypatch.setattr(cp, "_platform", lambda: "darwin")
    monkeypatch.setattr(cp, "_macos_calendar_authorized", lambda: True)
    monkeypatch.setattr(cp, "_load_routing", _routing_with_macos({}))
    assert cp.probe("calendar").state == "off"


def test_google_token_still_wins(monkeypatch):
    monkeypatch.setattr(cp, "_google_probe", lambda prefix: cp.ProbeResult("on"))
    monkeypatch.setattr(cp, "_platform", lambda: "linux")
    assert cp.probe("calendar").state == "on"
