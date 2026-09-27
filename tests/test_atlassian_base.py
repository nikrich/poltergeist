"""Tests for ghostbrain.connectors.atlassian._base — auth + slug helpers.

We don't mock requests here; the AtlassianClient HTTP path is exercised
by the per-connector tests via the higher-level connector mocks.
"""

from __future__ import annotations

import os

import pytest

from ghostbrain.connectors.atlassian._base import (
    AtlassianAuthError,
    auth_for_site,
    slug_for_host,
)


def test_slug_for_host_drops_subdomain_chain() -> None:
    assert slug_for_host("acme.atlassian.net") == "acme"
    assert slug_for_host("consulting.atlassian.net") == "consulting"


def test_auth_for_site_uses_site_specific_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_ACME", "site-token")
    monkeypatch.delenv("ATLASSIAN_TOKEN", raising=False)
    email, token = auth_for_site("acme.atlassian.net")
    assert email == "u@example.com"
    assert token == "site-token"


def test_auth_for_site_falls_back_to_default_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.delenv("ATLASSIAN_TOKEN_ACME", raising=False)
    monkeypatch.setenv("ATLASSIAN_TOKEN", "default-token")
    email, token = auth_for_site("acme.atlassian.net")
    assert token == "default-token"


def test_auth_for_site_normalizes_dashes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.setenv("ATLASSIAN_TOKEN_WORK_ACME", "the-token")
    email, token = auth_for_site("work-acme.atlassian.net")
    assert token == "the-token"


def test_auth_for_site_raises_when_missing_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLASSIAN_EMAIL", raising=False)
    with pytest.raises(AtlassianAuthError):
        auth_for_site("acme.atlassian.net")


def test_auth_for_site_raises_when_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_EMAIL", "u@example.com")
    monkeypatch.delenv("ATLASSIAN_TOKEN_ACME", raising=False)
    monkeypatch.delenv("ATLASSIAN_TOKEN", raising=False)
    with pytest.raises(AtlassianAuthError):
        auth_for_site("acme.atlassian.net")


def test_save_token_creates_file_owner_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostbrain.connectors.atlassian import _base

    opened: list[tuple] = []
    real_open = os.open

    def spy(path, flags, mode=0o777, *a, **k):
        opened.append((str(path), flags, mode))
        return real_open(path, flags, mode, *a, **k)

    monkeypatch.setattr(_base.os, "open", spy)
    p = _base.save_token("acme.atlassian.net", " tok \n")
    assert p.read_text(encoding="utf-8") == "tok"
    assert opened and opened[0][0] == str(p) and opened[0][2] == 0o600
    assert opened[0][1] & os.O_CREAT and opened[0][1] & os.O_TRUNC
    assert (p.stat().st_mode & 0o777) == 0o600


def test_save_token_tightens_existing_file(monkeypatch: pytest.MonkeyPatch) -> None:
    from ghostbrain.connectors.atlassian import _base

    p = _base.token_path("acme.atlassian.net")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("old-longer-token", encoding="utf-8")
    p.chmod(0o644)
    _base.save_token("acme.atlassian.net", "new")
    assert p.read_text(encoding="utf-8") == "new"
    assert (p.stat().st_mode & 0o777) == 0o600
