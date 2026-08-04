# tests/test_mcp_runtime.py
import os
import stat
import sys

import pytest

from ghostbrain.api import runtime


@pytest.fixture(autouse=True)
def _run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path / "run"))
    # Isolate the singleton lock too — _publish_descriptor now acquires a
    # "sidecar" flock under the state dir.
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
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


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows has no POSIX permission bits"
)
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


def test_publish_descriptor_writes_and_returns_lock_when_primary():
    """The primary sidecar wins the lock, publishes its descriptor, and
    returns the held lock for the caller to keep alive."""
    from ghostbrain.api.__main__ import _publish_descriptor

    lock = _publish_descriptor(port=40404, token="abc123")
    assert lock is not None, "primary must hold the sidecar lock"
    try:
        d = runtime.load_descriptor()
        assert d is not None
        assert d["port"] == 40404
        assert d["token"] == "abc123"
        assert d["pid"] == os.getpid()
    finally:
        runtime.release_singleton_lock(lock)


def test_publish_descriptor_skips_when_another_instance_holds_lock():
    """A second sidecar that can't win the lock must NOT publish — otherwise
    it clobbers the primary's descriptor (the 'not running' bug)."""
    from ghostbrain.api.__main__ import _publish_descriptor

    held = runtime.acquire_singleton_lock("sidecar")
    assert held is not None
    try:
        lock = _publish_descriptor(port=50505, token="secondary")
        assert lock is None, "second instance must not acquire the lock"
        assert runtime.load_descriptor() is None, "second instance must not publish"
    finally:
        runtime.release_singleton_lock(held)


def test_publish_descriptor_does_not_clobber_primary_descriptor():
    """With the primary holding the lock AND owning the descriptor, a second
    instance's publish attempt leaves the primary's descriptor untouched."""
    from ghostbrain.api.__main__ import _publish_descriptor

    held = runtime.acquire_singleton_lock("sidecar")
    assert held is not None
    runtime.write_descriptor(
        port=40404, token="primary", pid=os.getpid(),
        version="1.0.0", started_at="x",
    )
    try:
        lock = _publish_descriptor(port=50505, token="secondary")
        assert lock is None
        d = runtime.load_descriptor()
        assert d is not None
        assert d["port"] == 40404 and d["token"] == "primary"
    finally:
        runtime.release_singleton_lock(held)
