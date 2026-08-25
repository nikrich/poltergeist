"""POST /v1/recorder/{start,stop,clear}."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# darwin + win32 are supported backends; unsupported platforms (linux) get a
# designed 501 — covered by test_recorder_api_platform_guard.py, which DOES
# run everywhere. These behavioural tests assume a real darwin environment
# (state-file layout, ffmpeg pid semantics) so they only run there.
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin", reason="recorder behavioural tests assume darwin"
)


def _write_daemon_active(state_dir: Path, *, pid: int) -> None:
    """Seed ~/.ghostbrain/state/recorder.json with a daemon-owned recording."""
    (state_dir / "recorder.json").write_text(
        json.dumps({
            "active": {
                "event_id": "calendar:macos:Calendar:abc:1",
                "title": "Sprint Planning",
                "context": "work",
                "pid": pid,
                "wav_path": "/tmp/meeting.wav",
                "started_at": "2026-05-15T10:00:00+00:00",
                "scheduled_end": "2026-05-15T12:00:00+00:00",
            },
            "processed": {},
        }),
        encoding="utf-8",
    )


def test_stop_kills_daemon_owned_recording(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
) -> None:
    """Regression: stop() previously only inspected manual.state, so the UI
    Stop button silently failed (409) when the live recording was started by
    the calendar-driven daemon. It should stop capture in that case too.

    status()/stop() consult the audio backend (not audio_capture directly) so
    this works identically on darwin and win32 — mock get_backend() in the
    audio-factory module, since api/repo/recorder.py resolves it lazily from
    there."""
    _write_daemon_active(tmp_state_dir, pid=99999)

    fake_backend = MagicMock()
    fake_backend.capture_alive.return_value = True

    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend):
        res = client.post("/v1/recorder/stop", headers=auth_headers)

        assert res.status_code == 200, res.text
        fake_backend.stop_capture.assert_called_once_with(99999)


def test_stop_without_any_active_recording_returns_409(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = client.post("/v1/recorder/stop", headers=auth_headers)
    assert res.status_code == 409
