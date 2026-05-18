"""POST /v1/recorder/{start,stop,clear}."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


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
    the calendar-driven daemon. It should SIGINT ffmpeg in that case too."""
    _write_daemon_active(tmp_state_dir, pid=99999)

    with patch("ghostbrain.api.repo.recorder.audio_capture") as ac:
        ac.is_running.return_value = True

        res = client.post("/v1/recorder/stop", headers=auth_headers)

        assert res.status_code == 200, res.text
        ac.stop_capture.assert_called_once_with(99999)


def test_stop_without_any_active_recording_returns_409(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    res = client.post("/v1/recorder/stop", headers=auth_headers)
    assert res.status_code == 409
