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


@pytest.fixture(autouse=True)
def _isolate_recorder_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The recorder snapshots ``Path.home()`` into module constants at import —
    before ``_isolate_user_state`` swaps HOME — so without this, tests read
    and rewrite the REAL ``~/ghostbrain/recorder/manual.state`` and can
    SIGINT a live meeting's capture process (happened 2026-10-09). Point every
    one of them into the per-test sandbox. tests/test_recorder_sandbox.py
    fails if a new home-derived recorder path is added without being listed."""
    from ghostbrain.api.repo import recorder as repo
    from ghostbrain.recorder import config, daemon, manual, transcribe

    root = tmp_path / "home" / "ghostbrain" / "recorder"
    recordings = root / "recordings"
    for mod in (config, daemon, manual):
        monkeypatch.setattr(mod, "DEFAULT_RECORDINGS_DIR", recordings)
    monkeypatch.setattr(repo, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(repo, "STATE_FILE", root / "manual.state")
    monkeypatch.setattr(transcribe, "DEFAULT_MODEL_DIR", root / "models")


@pytest.fixture(autouse=True)
def _no_real_whisper_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recording-start code paths spin up live transcription; never launch a
    real whisper-server (and load a real model) from a test. Tests that need a
    server pass ``binary=`` or inject a ``server_factory``."""
    from ghostbrain.recorder import live, whisper_server

    monkeypatch.setattr(whisper_server, "BINARY", "ghostbrain-test-no-whisper-server")
    # Nor start a design session for every recording a test begins; design
    # tests drive the listener explicitly.
    monkeypatch.setattr(live, "_on_begin", [])
    yield
    live.stop_all()
