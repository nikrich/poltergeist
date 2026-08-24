"""AudioBackend factory + darwin delegation. WASAPI thread tests live here too (Task 4)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ghostbrain.recorder.audio import get_backend
from ghostbrain.recorder.audio.base import RouteHandle, UnsupportedBackend
from ghostbrain.recorder.audio.darwin import DarwinBackend


def test_factory_darwin():
    assert isinstance(get_backend("darwin"), DarwinBackend)


def test_factory_linux_unsupported():
    backend = get_backend("linux")
    assert isinstance(backend, UnsupportedBackend)
    ok, missing = backend.preflight()
    assert ok is False
    assert any("not supported" in m for m in missing)


def test_darwin_begin_route_switches_and_remembers_previous():
    with patch("ghostbrain.recorder.audio.darwin.audio_switcher") as sw:
        sw.current_output.return_value = "MacBook Pro Speakers"
        handle = DarwinBackend().begin_meeting_route("Ghost Brain", "")
    sw.switch_to.assert_called_once_with("Ghost Brain")
    assert handle == RouteHandle(previous_output="MacBook Pro Speakers", switched=True)


def test_darwin_begin_route_noop_when_already_on_device():
    with patch("ghostbrain.recorder.audio.darwin.audio_switcher") as sw:
        sw.current_output.return_value = "Ghost Brain"
        handle = DarwinBackend().begin_meeting_route("Ghost Brain", "")
    sw.switch_to.assert_not_called()
    assert handle.switched is False


def test_darwin_end_route_restores():
    with patch("ghostbrain.recorder.audio.darwin.audio_switcher") as sw:
        DarwinBackend().end_meeting_route(
            RouteHandle(previous_output="MacBook Pro Speakers", switched=True)
        )
    sw.switch_to.assert_called_once_with("MacBook Pro Speakers")


def test_darwin_end_route_noop_when_not_switched():
    with patch("ghostbrain.recorder.audio.darwin.audio_switcher") as sw:
        DarwinBackend().end_meeting_route(RouteHandle(previous_output="", switched=False))
    sw.switch_to.assert_not_called()


def test_darwin_capture_delegates(tmp_path: Path):
    with patch("ghostbrain.recorder.audio.darwin.audio_capture") as cap:
        DarwinBackend().start_capture(tmp_path / "x.wav")
        cap.start_capture.assert_called_once_with(tmp_path / "x.wav", log_path=None)
