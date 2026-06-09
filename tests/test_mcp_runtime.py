# tests/test_mcp_runtime.py
import os
import stat

import pytest

from ghostbrain.api import runtime


@pytest.fixture(autouse=True)
def _run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path / "run"))
    yield


def test_write_then_load_round_trips():
    runtime.write_descriptor(
        port=51234,
        token="deadbeef",
        pid=os.getpid(),
        version="1.0.0",
        started_at="2026-06-09T09:30:15+02:00",
    )
    d = runtime.load_descriptor()
    assert d is not None
    assert d["port"] == 51234
    assert d["token"] == "deadbeef"
    assert d["pid"] == os.getpid()
    assert d["version"] == "1.0.0"


def test_descriptor_file_is_chmod_600():
    runtime.write_descriptor(
        port=1, token="t", pid=os.getpid(), version="1.0.0", started_at="x"
    )
    mode = stat.S_IMODE(os.stat(runtime.descriptor_path()).st_mode)
    assert mode == 0o600


def test_load_missing_returns_none():
    assert runtime.load_descriptor() is None


def test_load_unparseable_returns_none():
    runtime.run_dir().mkdir(parents=True, exist_ok=True)
    runtime.descriptor_path().write_text("{not json")
    assert runtime.load_descriptor() is None


def test_load_dead_pid_returns_none():
    # PID 999999 is virtually certain not to exist.
    runtime.write_descriptor(
        port=1, token="t", pid=999999, version="1.0.0", started_at="x"
    )
    assert runtime.load_descriptor() is None


def test_remove_is_idempotent():
    runtime.write_descriptor(
        port=1, token="t", pid=os.getpid(), version="1.0.0", started_at="x"
    )
    runtime.remove_descriptor()
    runtime.remove_descriptor()  # second call must not raise
    assert runtime.load_descriptor() is None
