"""Shared fixture for docs-library tests: a temp vault with two contexts and two projects."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def lib_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    (v / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    from ghostbrain.api.repo import projects

    projects.create_project("work", "Payments")
    projects.create_project("work", "Claims")
    monkeypatch.setattr(
        "ghostbrain.api.repo.attachment_caption.caption_image", lambda path: "a diagram"
    )
    try:
        from ghostbrain.api.repo.doc_library import index

        index.invalidate()
    except ImportError:  # index arrives in Task 3
        pass
    return v
