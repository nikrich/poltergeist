"""Recorder API repo functions must return a clean 'unsupported' when the
audio backend is unsupported (Linux today) and must fall through to normal
logic on any platform with a real backend (darwin, win32)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from ghostbrain.api.repo import recorder as recorder_repo


@pytest.fixture
def unsupported_platform():
    """Patch sys.platform inside the audio backend factory to an unsupported value."""
    with patch("ghostbrain.recorder.audio.sys") as mock_sys:
        mock_sys.platform = "linux"
        yield mock_sys


def test_status_raises_on_unsupported_platform(unsupported_platform):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.status()


def test_start_raises_on_unsupported_platform(unsupported_platform):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.start(title=None, context=None)


def test_stop_raises_on_unsupported_platform(unsupported_platform):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.stop()


def test_clear_raises_on_unsupported_platform(unsupported_platform):
    with pytest.raises(recorder_repo.RecorderUnsupportedError):
        recorder_repo.clear()


def test_status_works_on_supported_platform():
    """Sanity: when the backend is supported (darwin here), status() falls
    through to its normal logic (which on a clean test env returns the
    'idle' phase, NOT raises)."""
    with patch("ghostbrain.recorder.audio.sys") as mock_sys:
        mock_sys.platform = "darwin"
        # status() reads state files — patch any I/O that would fail in test env.
        with patch("ghostbrain.api.repo.recorder._read_state", return_value=None), \
             patch("ghostbrain.api.repo.recorder._daemon_active", return_value=None):
            result = recorder_repo.status()
    # status() returns a dict; we just verify it didn't raise UnsupportedError.
    assert isinstance(result, dict)
