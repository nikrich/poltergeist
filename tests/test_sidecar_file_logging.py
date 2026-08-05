"""Persistent sidecar logs under <run_dir>/logs/sidecar.log.

Before this existed, the sidecar kept only a 4KB in-memory stderr tail —
every incident that survived a restart was undiagnosable. The file handler
must be idempotent (uvicorn reload / repeated create_app must not stack
duplicate handlers).
"""
from __future__ import annotations

import logging
from pathlib import Path

from ghostbrain.api import runtime


def test_setup_file_logging_writes_and_rotates_config(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path))
    handler = runtime.setup_file_logging()
    try:
        logging.getLogger("ghostbrain.test").warning("hello from the test")
        handler.flush()
        log_file = tmp_path / "logs" / "sidecar.log"
        assert log_file.exists()
        body = log_file.read_text()
        assert "hello from the test" in body
        assert "ghostbrain.test" in body
        # Rotation config: bounded size with backups, so logs can't eat the disk.
        assert handler.maxBytes > 0
        assert handler.backupCount >= 1
    finally:
        logging.getLogger().removeHandler(handler)


def test_setup_file_logging_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path))
    h1 = runtime.setup_file_logging()
    h2 = runtime.setup_file_logging()
    try:
        assert h1 is h2
        root = logging.getLogger()
        ours = [h for h in root.handlers if getattr(h, "_ghostbrain_file_log", False)]
        assert len(ours) == 1
    finally:
        logging.getLogger().removeHandler(h1)


def test_remove_descriptor_only_deletes_own_pid(tmp_path: Path, monkeypatch) -> None:
    """A foreign process exiting must not delete the live sidecar's descriptor
    (2026-08-05: unguarded unlink took the vault offline while the sidecar
    was healthy)."""
    import json
    import os

    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path))
    p = tmp_path / "sidecar.json"
    p.write_text(json.dumps({"port": 1, "token": "t", "pid": os.getpid() + 1}))
    runtime.remove_descriptor()
    assert p.exists(), "foreign-owned descriptor was deleted"

    p.write_text(json.dumps({"port": 1, "token": "t", "pid": os.getpid()}))
    runtime.remove_descriptor()
    assert not p.exists(), "own descriptor should be removed"
