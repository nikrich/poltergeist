"""Recorder dependency preflight: shared audio-backend + transcription checks.

Moved out of ``ghostbrain.scheduler_jobs`` (which re-exports
``recorder_prereqs_ok`` for backward compatibility) so both the calendar
daemon and the manual /v1/recorder/start route can preflight before doing
anything that would otherwise surface as a bare OS-level error.
"""
from __future__ import annotations

import shutil


def _model_present() -> bool:
    """Delegates to transcribe._resolve_model so this honours
    GHOSTBRAIN_WHISPER_MODEL the same way the daemon's actual transcription
    call does — a globbed check of DEFAULT_MODEL_DIR alone reported "no
    model" even when the env var pointed at a valid model elsewhere."""
    from ghostbrain.recorder.transcribe import TranscribeError, _resolve_model
    try:
        _resolve_model(None)
    except TranscribeError:
        return False
    return True


def recorder_prereqs_ok() -> tuple[bool, list[str]]:
    """Backend preflight + shared transcription prereqs."""
    from ghostbrain.recorder.audio import get_backend

    _ok, missing = get_backend().preflight()
    missing = list(missing)
    if shutil.which("whisper-cli") is None:
        missing.append(
            "whisper-cli not on PATH (macOS: brew install whisper-cpp; "
            "Windows: install whisper.cpp and add it to PATH)"
        )
    if not _model_present():
        missing.append(
            "no whisper model in ~/ghostbrain/recorder/models/ (any ggml-*.bin); "
            "on corporate networks download it via browser/approved channel, "
            "not curl"
        )
    return (not missing, missing)
