"""recorder.config is the single source of recorder defaults."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.recorder import config as rcfg


def test_defaults_are_shared_by_daemon_and_manual():
    from ghostbrain.recorder import daemon, manual
    assert daemon.DEFAULT_RECORDINGS_DIR == rcfg.DEFAULT_RECORDINGS_DIR
    assert manual.DEFAULT_RECORDINGS_DIR == rcfg.DEFAULT_RECORDINGS_DIR
    assert daemon.DEFAULT_AUDIO_DEVICE == rcfg.RECORDER_DEFAULTS["audio_device"]
    assert manual.DEFAULT_MANUAL_CONTEXT == rcfg.RECORDER_DEFAULTS["manual_context"]


def test_coercion_helpers():
    assert rcfg.capture_backend_from({"capture_backend": "Native"}) == "native"
    assert rcfg.capture_backend_from({"capture_backend": "bogus"}) == "auto"
    assert rcfg.capture_backend_from(None) == "auto"
    assert rcfg.slide_fallback_from({"slide_fallback": "DISPLAY"}) == "display"
    assert rcfg.slide_fallback_from({}) == "ask"
    assert rcfg.slide_fps_from({"slide_fps": 99}) == 5
    assert rcfg.slide_fps_from({"slide_fps": "x"}) == 1
    assert rcfg.slide_min_words_from({"slide_min_words": -4}) == 0
    assert rcfg.capture_slides_from({"capture_slides": False}) is False


def test_load_recorder_block_reads_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    (tmp_path / "90-meta").mkdir()
    (tmp_path / "90-meta" / "config.yaml").write_text(
        "recorder:\n  capture_backend: blackhole\n  slide_fps: 2\n"
    )
    rec = rcfg.load_recorder_block()
    assert rcfg.capture_backend_from(rec) == "blackhole"
    assert rcfg.slide_fps_from(rec) == 2
    (tmp_path / "90-meta" / "config.yaml").write_text("not: [valid")
    assert rcfg.load_recorder_block() == {}


def test_api_settings_defaults_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    from ghostbrain.api.repo import settings as api_settings
    monkeypatch.setattr(api_settings, "effective_capture_backend",
                        lambda raw=None, platform=None: "unsupported")
    got = api_settings.get_recorder_settings()
    for key in ("enabled", "manual_context", "capture_backend", "capture_slides",
                "slide_fps", "slide_fallback"):
        assert got[key] == rcfg.RECORDER_DEFAULTS[key]
    assert got["excluded_titles"] == rcfg.RECORDER_DEFAULTS["excluded_titles"]
