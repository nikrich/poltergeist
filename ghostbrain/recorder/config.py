"""Single home for the ``recorder:`` block of ``<vault>/90-meta/config.yaml``.

The daemon, the manual-recording flow and the settings API all read the same
block. Before this module each of them carried its own copy of the defaults,
so a new knob had to be added in three or four places. Keep every default
here and have callers read through ``RECORDER_DEFAULTS`` / ``load_recorder_block``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ghostbrain.paths import vault_path

DEFAULT_RECORDINGS_DIR = Path.home() / "ghostbrain" / "recorder" / "recordings"

# ``capture_backend`` values (macOS only; Windows always uses WASAPI).
#   auto      — native ScreenCaptureKit helper when present + permitted, else blackhole
#   native    — force the helper (preflight fails loudly if it can't run)
#   blackhole — legacy ffmpeg + BlackHole + SwitchAudioSource path
CAPTURE_BACKENDS = ("auto", "native", "blackhole")

# What the native helper does when no meeting-app window is on screen.
#   ask     — record audio now, ask the user (desktop prompt) whether to capture the screen
#   display — capture the whole display without asking
#   audio   — never capture video unless a meeting window appears
SLIDE_FALLBACKS = ("ask", "display", "audio")

RECORDER_DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "poll_interval_seconds": 30,
    "end_grace_seconds": 60,
    "audio_device": "Ghost Brain",
    "fallback_output": "",
    "excluded_titles": ["Focus", "focus"],
    "excluded_contexts": [],
    "included_contexts": [],
    "manual_enabled": True,
    "manual_context": "personal",
    "recordings_dir": str(DEFAULT_RECORDINGS_DIR),
    "capture_backend": "auto",
    "capture_slides": True,
    "slide_fps": 1,
    "slide_min_words": 8,
    "slide_fallback": "ask",
}


def config_path() -> Path:
    return vault_path() / "90-meta" / "config.yaml"


def load_config_yaml() -> dict[str, Any]:
    """Whole ``config.yaml`` as a dict (``{}`` when missing/unreadable)."""
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def load_recorder_block() -> dict[str, Any]:
    """The raw ``recorder:`` mapping (``{}`` when absent). Values are NOT
    defaulted — use :func:`recorder_value` for that."""
    rec = load_config_yaml().get("recorder")
    return dict(rec) if isinstance(rec, dict) else {}


def recorder_value(rec: dict[str, Any] | None, key: str) -> Any:
    """``rec[key]`` with the shared default when the key is missing/None."""
    if rec is not None and rec.get(key) is not None:
        return rec[key]
    return RECORDER_DEFAULTS[key]


def capture_backend_from(rec: dict[str, Any] | None) -> str:
    value = str(recorder_value(rec, "capture_backend")).strip().lower()
    return value if value in CAPTURE_BACKENDS else "auto"


def slide_fallback_from(rec: dict[str, Any] | None) -> str:
    value = str(recorder_value(rec, "slide_fallback")).strip().lower()
    return value if value in SLIDE_FALLBACKS else "ask"


def capture_slides_from(rec: dict[str, Any] | None) -> bool:
    return bool(recorder_value(rec, "capture_slides"))


def slide_fps_from(rec: dict[str, Any] | None) -> int:
    try:
        fps = int(recorder_value(rec, "slide_fps"))
    except (TypeError, ValueError):
        fps = int(RECORDER_DEFAULTS["slide_fps"])
    return min(5, max(1, fps))


def slide_min_words_from(rec: dict[str, Any] | None) -> int:
    try:
        n = int(recorder_value(rec, "slide_min_words"))
    except (TypeError, ValueError):
        n = int(RECORDER_DEFAULTS["slide_min_words"])
    return max(0, n)
