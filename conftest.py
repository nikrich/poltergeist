"""Root conftest: user-state sandbox applied to all pytest trees (tests/ + ghostbrain/api/tests/)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every home-relative path the code reads at a per-test temp dir.

    Tests that need the real home (none today) must opt out explicitly with
    ``monkeypatch.delenv``. REAL_HOME_FOR_TEST lets a test assert the sandbox held.
    """
    monkeypatch.setenv("REAL_HOME_FOR_TEST", str(Path.home()))
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))  # Path.home() on Windows
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("VAULT_PATH", str(tmp_path / "vault"))
    # accounts.yaml seeding would otherwise shell out to `gh` and open the
    # MSAL keychain cache; tests opt back in explicitly.
    monkeypatch.setenv("GHOSTBRAIN_ACCOUNTS_LIVE_SEED", "0")


@pytest.fixture(autouse=True)
def _no_real_msal_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never open the real MSAL token cache (OS keychain) from a test.

    Sign-in flows best-effort list the cached Microsoft accounts; tests that
    exercise that patch ``auth._build_app`` / ``auth.cached_usernames``.
    """
    from ghostbrain.connectors.microsoft.graph import auth as ms_auth

    def _refuse() -> None:
        raise RuntimeError("real MSAL token cache is disabled in tests")

    monkeypatch.setattr(ms_auth, "_build_token_cache", _refuse)
