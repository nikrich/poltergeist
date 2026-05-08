"""Shared pytest fixtures."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


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
