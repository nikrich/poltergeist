"""Tests for Microsoft Graph auth helpers. MSAL is mocked — no network,
no device-code flow. Pure path + scope + error logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_scopes_are_the_union_of_all_three_connectors() -> None:
    from ghostbrain.connectors.microsoft.graph import auth
    assert set(auth.SCOPES) == {
        "Mail.Read",
        "Chat.Read",
        "Calendars.Read",
        "OnlineMeetings.Read",
        "OnlineMeetingTranscript.Read.All",
    }


def test_cache_location_lives_under_state_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    from ghostbrain.connectors.microsoft.graph import auth
    loc = auth.cache_location()
    assert loc == tmp_path / "microsoft" / "token_cache.bin"


def test_resolve_app_config_prefers_routing_over_default() -> None:
    from ghostbrain.connectors.microsoft.graph import auth
    cid, tid = auth.resolve_app_config(
        {"client_id": "cid-override", "tenant_id": "tid-override"}
    )
    assert cid == "cid-override"
    assert tid == "tid-override"


def test_resolve_app_config_raises_when_unconfigured(monkeypatch) -> None:
    monkeypatch.delenv("MS_GRAPH_CLIENT_ID", raising=False)
    monkeypatch.delenv("MS_GRAPH_TENANT_ID", raising=False)
    from ghostbrain.connectors.microsoft.graph import auth
    with pytest.raises(auth.MicrosoftAuthError):
        auth.resolve_app_config({})


def test_get_token_raises_when_no_cached_account(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    from ghostbrain.connectors.microsoft.graph import auth

    fake_app = MagicMock()
    fake_app.get_accounts.return_value = []
    with patch.object(auth, "_build_app", return_value=fake_app):
        with pytest.raises(auth.MicrosoftAuthError):
            auth.get_token({})


def test_get_token_returns_cached_token_silently(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    from ghostbrain.connectors.microsoft.graph import auth

    fake_app = MagicMock()
    fake_app.get_accounts.return_value = [{"username": "me@sanlam.com"}]
    fake_app.acquire_token_silent.return_value = {"access_token": "tok-123"}
    with patch.object(auth, "_build_app", return_value=fake_app):
        assert auth.get_token({}) == "tok-123"
