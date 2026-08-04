"""Recorder API endpoints must return a clean 'unsupported' on non-darwin."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ghostbrain.api.repo import recorder as recorder_repo


@pytest.fixture
def non_darwin():
    """Patch sys.platform inside the recorder repo to a non-darwin value."""
    with patch("ghostbrain.api.repo.recorder.sys") as mock_sys:
        mock_sys.platform = "linux"
        yield mock_sys


def test_status_raises_on_non_darwin(non_darwin):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.status()


def test_start_raises_on_non_darwin(non_darwin):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.start(title=None, context=None)


def test_stop_raises_on_non_darwin(non_darwin):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.stop()


def test_clear_raises_on_non_darwin(non_darwin):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.clear()


def test_status_works_on_darwin():
    """Sanity: when platform is darwin, status() falls through to its normal logic
    (which on a clean test env returns the 'idle' phase, NOT raises)."""
    with patch("ghostbrain.api.repo.recorder.sys") as mock_sys:
        mock_sys.platform = "darwin"
        # status() reads state files — patch any I/O that would fail in test env.
        with patch("ghostbrain.api.repo.recorder._read_state", return_value=None), \
             patch("ghostbrain.api.repo.recorder._daemon_active", return_value=None):
            result = recorder_repo.status()
    # status() returns a dict; we just verify it didn't raise UnsupportedError.
    assert isinstance(result, dict)
