"""Shared pytest fixtures."""

from __future__ import annotations

import importlib
import os
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


@pytest.fixture()
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Boot a temporary vault and reload modules that cache vault_path()."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    import ghostbrain.paths as _paths
    importlib.reload(_paths)
    # Reload modules that import from paths so they see the new VAULT_PATH.
    for mod in (
        "ghostbrain.profile.claude_md",
        "ghostbrain.profile.diff",
        "ghostbrain.profile.apply",
        "ghostbrain.profile.decay",
        "ghostbrain.metrics.staleness",
        "ghostbrain.metrics.checkins",
        "ghostbrain.metrics.snapshot",
        "ghostbrain.semantic.index",
        "ghostbrain.semantic.refresh",
        "ghostbrain.worker.audit",
        "ghostbrain.worker.note_generator",
        "ghostbrain.worker.router",
        "ghostbrain.worker.extractor",
        "ghostbrain.worker.pipeline",
        "ghostbrain.worker.digest",
        "ghostbrain.worker.main",
    ):
        try:
            m = importlib.import_module(mod)
            importlib.reload(m)
        except ModuleNotFoundError:
            pass
    from ghostbrain.bootstrap import bootstrap
    bootstrap(tmp_path)
    return tmp_path


@pytest.fixture()
def vault_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary vault directory without bootstrapping.

    Used for testing bootstrap logic itself (e.g., ensure_vault()).
    """
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    import ghostbrain.paths as _paths
    importlib.reload(_paths)
    # Reload modules that import from paths so they see the new VAULT_PATH.
    for mod in (
        "ghostbrain.profile.claude_md",
        "ghostbrain.profile.diff",
        "ghostbrain.profile.apply",
        "ghostbrain.profile.decay",
        "ghostbrain.metrics.staleness",
        "ghostbrain.metrics.checkins",
        "ghostbrain.metrics.snapshot",
        "ghostbrain.semantic.index",
        "ghostbrain.semantic.refresh",
        "ghostbrain.worker.audit",
        "ghostbrain.worker.note_generator",
        "ghostbrain.worker.router",
        "ghostbrain.worker.extractor",
        "ghostbrain.worker.pipeline",
        "ghostbrain.worker.digest",
        "ghostbrain.worker.main",
    ):
        try:
            m = importlib.import_module(mod)
            importlib.reload(m)
        except ModuleNotFoundError:
            pass
    return tmp_path
