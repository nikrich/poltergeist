"""Recorder must report unsupported on non-darwin so users don't hit
ffmpeg/BlackHole crashes downstream."""
from __future__ import annotations

from unittest.mock import patch

from ghostbrain.scheduler_jobs import recorder_prereqs_ok


def test_recorder_prereqs_unsupported_on_linux():
    with patch("ghostbrain.scheduler_jobs.sys") as mock_sys:
        mock_sys.platform = "linux"
        ok, missing = recorder_prereqs_ok()
    assert ok is False
    assert any("macOS-only" in m for m in missing)


def test_recorder_prereqs_unsupported_on_windows():
    with patch("ghostbrain.scheduler_jobs.sys") as mock_sys:
        mock_sys.platform = "win32"
        ok, missing = recorder_prereqs_ok()
    assert ok is False
    assert any("macOS-only" in m for m in missing)


def test_recorder_prereqs_runs_existing_checks_on_darwin():
    """On darwin we should still get the ffmpeg check, not the platform short-circuit."""
    with patch("ghostbrain.scheduler_jobs.sys") as mock_sys, \
         patch("ghostbrain.scheduler_jobs.shutil.which", return_value=None):
        mock_sys.platform = "darwin"
        ok, missing = recorder_prereqs_ok()
    assert ok is False
    # ffmpeg check should fire, NOT the platform check.
    assert any("ffmpeg" in m for m in missing)
    assert not any("macOS-only" in m for m in missing)
