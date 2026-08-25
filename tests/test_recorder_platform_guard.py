"""Recorder support is decided by the audio backend, not raw platform:
darwin + win32 are supported (with per-backend prereqs), linux is not."""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

from ghostbrain.scheduler_jobs import recorder_prereqs_ok


def test_linux_unsupported():
    with patch("ghostbrain.recorder.audio.sys") as mock_sys:
        mock_sys.platform = "linux"
        ok, missing = recorder_prereqs_ok()
    assert ok is False
    assert any("not supported" in m for m in missing)


def test_win32_missing_deps_lists_actionable_items(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", None)
    with patch("ghostbrain.recorder.audio.sys") as mock_sys, \
         patch("ghostbrain.scheduler_jobs.shutil.which", return_value=None):
        mock_sys.platform = "win32"
        ok, missing = recorder_prereqs_ok()
    assert ok is False
    assert any("pyaudiowpatch" in m for m in missing)
    assert any("whisper-cli" in m for m in missing)
    assert not any("macOS-only" in m for m in missing)


def test_win32_with_deps_supported(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", types.ModuleType("pyaudiowpatch"))
    model = tmp_path / "ggml-small.en.bin"
    model.write_bytes(b"x")
    monkeypatch.setattr("ghostbrain.scheduler_jobs._model_present",
                        lambda: True)
    with patch("ghostbrain.recorder.audio.sys") as mock_sys, \
         patch("ghostbrain.scheduler_jobs.shutil.which", return_value="/bin/whisper-cli"):
        mock_sys.platform = "win32"
        ok, missing = recorder_prereqs_ok()
    assert ok is True, missing


def test_darwin_ffmpeg_check_still_fires():
    # NOTE: ghostbrain.recorder.audio.darwin.shutil and ghostbrain.scheduler_jobs.shutil
    # are the same stdlib `shutil` module object, so patching `.which` on both targets
    # separately would have the second patch silently clobber the first. Use one
    # argument-aware patch instead so ffmpeg (darwin preflight) and whisper-cli
    # (scheduler_jobs) can report different results.
    def which_side_effect(tool):
        return None if tool == "ffmpeg" else "/bin/whisper-cli"

    with patch("ghostbrain.recorder.audio.sys") as mock_sys, \
         patch("ghostbrain.scheduler_jobs.shutil.which", side_effect=which_side_effect), \
         patch("ghostbrain.scheduler_jobs._model_present", lambda: True):
        mock_sys.platform = "darwin"
        ok, missing = recorder_prereqs_ok()
    assert ok is False
    assert any("ffmpeg" in m for m in missing)
