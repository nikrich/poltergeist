"""M1: manual.run_recovery_pass's stale-pid liveness check must go through
the platform AudioBackend (get_backend().capture_alive), not
audio_capture.is_running directly — on Windows, os.kill(pid, 0) (what
is_running does under the hood) can terminate the target process instead
of just probing it."""
from __future__ import annotations

from unittest.mock import MagicMock

from ghostbrain.recorder import manual


def test_recovery_pass_checks_liveness_via_backend_capture_alive(
    tmp_path, monkeypatch,
):
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    state_file = recordings_dir.parent / "manual.state"
    state_file.write_text("4242\n", encoding="utf-8")

    fake_backend = MagicMock()
    fake_backend.capture_alive.return_value = True
    monkeypatch.setattr(manual, "get_backend", lambda: fake_backend, raising=False)

    cfg = manual.ManualConfig(
        enabled=True, context="personal", recordings_dir=recordings_dir,
    )
    result = manual.run_recovery_pass(cfg)

    fake_backend.capture_alive.assert_called_once_with(4242)
    # A real active recording (backend says alive) -> leave the directory
    # alone, nothing recovered.
    assert result == []


def test_recovery_pass_proceeds_when_backend_reports_pid_dead(
    tmp_path, monkeypatch,
):
    recordings_dir = tmp_path / "recordings"
    recordings_dir.mkdir()
    state_file = recordings_dir.parent / "manual.state"
    state_file.write_text("4242\n", encoding="utf-8")

    fake_backend = MagicMock()
    fake_backend.capture_alive.return_value = False
    monkeypatch.setattr(manual, "get_backend", lambda: fake_backend, raising=False)

    cfg = manual.ManualConfig(
        enabled=True, context="personal", recordings_dir=recordings_dir,
    )
    # No orphan WAVs present -> nothing recovered, but the liveness check
    # (and only the liveness check) must have consulted the backend.
    result = manual.run_recovery_pass(cfg)

    fake_backend.capture_alive.assert_called_once_with(4242)
    assert result == []
