"""Native-capture settings + helper endpoints (platform-neutral: the helper
probe and backend are mocked)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from ghostbrain.recorder.audio.base import CaptureUnavailableError
from ghostbrain.recorder.audio.darwin_native import HelperProbe

_OK_PROBE = HelperProbe(
    found=True, path="/Applications/Poltergeist.app/Contents/Resources/bin/ghostbrain-capture",
    ok=True, code=0, reason="ok", macos_version="15.6", macos_supported=True,
    screen_recording="granted", microphone="granted",
)
_DENIED_PROBE = HelperProbe(
    found=True, path="/x/ghostbrain-capture", ok=False, code=4,
    reason="Screen Recording permission not granted", macos_version="15.6",
    macos_supported=True, screen_recording="denied", microphone="granted",
)


def test_settings_roundtrip(client: TestClient, auth_headers: dict[str, str], tmp_vault: Path):
    with patch("ghostbrain.api.repo.settings.effective_capture_backend", return_value="native"):
        res = client.get("/v1/settings/recorder", headers=auth_headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["capture_backend"] == "auto"
        assert body["capture_slides"] is True
        assert body["slide_fps"] == 1
        assert body["slide_fallback"] == "ask"
        assert body["capture_backend_effective"] == "native"

        res = client.post("/v1/settings/recorder", headers=auth_headers, json={
            "capture_backend": "blackhole", "capture_slides": False,
            "slide_fps": 2, "slide_fallback": "display",
        })
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["capture_backend"] == "blackhole"
        assert body["capture_slides"] is False
        assert body["slide_fps"] == 2
        assert body["slide_fallback"] == "display"

    import yaml
    on_disk = yaml.safe_load((tmp_vault / "90-meta" / "config.yaml").read_text())["recorder"]
    assert on_disk["capture_backend"] == "blackhole"
    assert on_disk["slide_fallback"] == "display"


def test_settings_validation(client: TestClient, auth_headers: dict[str, str]):
    assert client.post("/v1/settings/recorder", headers=auth_headers,
                       json={"capture_backend": "bogus"}).status_code == 422
    assert client.post("/v1/settings/recorder", headers=auth_headers,
                       json={"slide_fps": 0}).status_code == 422
    assert client.post("/v1/settings/recorder", headers=auth_headers,
                       json={"slide_fps": 9}).status_code == 422
    assert client.post("/v1/settings/recorder", headers=auth_headers,
                       json={"slide_fallback": "maybe"}).status_code == 422


def test_start_maps_capture_unavailable_to_412(client: TestClient, auth_headers: dict[str, str]):
    fake_backend = MagicMock()
    fake_backend.name = "native"
    fake_backend.start_capture.side_effect = CaptureUnavailableError(
        "Screen Recording permission not granted"
    )
    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend), \
         patch("ghostbrain.api.repo.recorder._current_calendar_event", return_value=None):
        res = client.post("/v1/recorder/start", headers=auth_headers, json={})
    assert res.status_code == 412
    assert "Screen Recording" in res.json()["detail"]


def test_status_reports_backend_and_awaiting_choice(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path, monkeypatch,
):
    from ghostbrain.api.repo import recorder as repo
    state_file = tmp_path / "manual.state"
    monkeypatch.setattr(repo, "STATE_FILE", state_file)
    state_file.write_text(json.dumps({
        "phase": "recording", "pid": 4242, "wavPath": "/tmp/x.wav",
        "captureBackend": "native", "awaitingTargetChoice": True,
    }))
    fake_backend = MagicMock()
    fake_backend.capture_alive.return_value = True
    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend):
        res = client.get("/v1/recorder/status", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["captureBackend"] == "native"
    assert body["awaitingTargetChoice"] is True


def test_status_lists_capture_windows_while_awaiting(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path, monkeypatch,
):
    from ghostbrain.api.repo import recorder as repo
    from ghostbrain.recorder.audio.darwin_native import frames_dir_for
    wav = tmp_path / "x.wav"
    frames = frames_dir_for(wav)
    frames.mkdir()
    (frames / "windows.json").write_text(json.dumps({"version": 1, "windows": [
        {"window_id": 16392, "app": "com.googlecode.iterm2", "app_name": "iTerm2",
         "title": "shell", "width": 1200, "height": 800, "candidate": False},
        {"window_id": 0, "app": "bad", "title": "skipped"},
    ]}))
    state_file = tmp_path / "manual.state"
    monkeypatch.setattr(repo, "STATE_FILE", state_file)
    state_file.write_text(json.dumps({
        "phase": "recording", "pid": 4242, "wavPath": str(wav),
        "captureBackend": "native", "awaitingTargetChoice": True,
    }))
    fake_backend = MagicMock()
    fake_backend.capture_alive.return_value = True
    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend), \
         patch("ghostbrain.api.repo.recorder.sys") as fake_sys:
        fake_sys.platform = "darwin"
        res = client.get("/v1/recorder/status", headers=auth_headers)
    body = res.json()
    assert body["awaitingTargetChoice"] is True
    assert body["captureWindows"] == [{
        "windowId": 16392, "app": "com.googlecode.iterm2", "appName": "iTerm2",
        "title": "shell", "width": 1200, "height": 800, "candidate": False,
    }]


def test_capture_target_writes_control_file_for_manual_recording(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path, monkeypatch,
):
    from ghostbrain.api.repo import recorder as repo
    from ghostbrain.recorder.audio.darwin_native import control_file_for
    wav = tmp_path / "x.wav"
    state_file = tmp_path / "manual.state"
    monkeypatch.setattr(repo, "STATE_FILE", state_file)
    state_file.write_text(json.dumps({
        "phase": "recording", "pid": 4242, "wavPath": str(wav),
        "captureBackend": "native", "awaitingTargetChoice": True,
    }))
    fake_backend = MagicMock()
    fake_backend.capture_alive.return_value = True
    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend), \
         patch("ghostbrain.api.repo.recorder.sys") as fake_sys:
        fake_sys.platform = "darwin"
        res = client.post("/v1/recorder/capture/target", headers=auth_headers,
                          json={"choice": "window", "window_id": 16392})
        assert res.status_code == 200, res.text
        assert json.loads(control_file_for(wav).read_text()) == {
            "target": "window", "window_id": 16392,
        }
        assert res.json()["awaitingTargetChoice"] is False
        assert json.loads(state_file.read_text())["awaitingTargetChoice"] is False

        # window without id → 422; display overwrites the control file
        state_file.write_text(json.dumps({
            "phase": "recording", "pid": 4242, "wavPath": str(wav),
            "captureBackend": "native", "awaitingTargetChoice": True,
        }))
        assert client.post("/v1/recorder/capture/target", headers=auth_headers,
                           json={"choice": "window"}).status_code == 422
        res = client.post("/v1/recorder/capture/target", headers=auth_headers,
                          json={"choice": "display"})
        assert res.status_code == 200
        assert json.loads(control_file_for(wav).read_text()) == {"target": "display"}


def test_capture_target_without_recording_is_409(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path, monkeypatch,
):
    from ghostbrain.api.repo import recorder as repo
    monkeypatch.setattr(repo, "STATE_FILE", tmp_path / "manual.state")
    fake_backend = MagicMock()
    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend), \
         patch("ghostbrain.api.repo.recorder.sys") as fake_sys:
        fake_sys.platform = "darwin"
        res = client.post("/v1/recorder/capture/target", headers=auth_headers,
                          json={"choice": "audio"})
    assert res.status_code == 409


def test_request_permissions_returns_probe(client: TestClient, auth_headers: dict[str, str]):
    fake_backend = MagicMock()
    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend), \
         patch("ghostbrain.api.repo.recorder.sys") as fake_sys, \
         patch("ghostbrain.recorder.audio.darwin_native.request_permissions",
               return_value=_OK_PROBE):
        fake_sys.platform = "darwin"
        res = client.post("/v1/recorder/capture/request-permissions", headers=auth_headers)
    assert res.status_code == 200, res.text
    assert res.json()["screen_recording"] == "granted"


def test_request_permissions_off_darwin_is_501(client: TestClient, auth_headers: dict[str, str]):
    fake_backend = MagicMock()
    with patch("ghostbrain.recorder.audio.get_backend", return_value=fake_backend), \
         patch("ghostbrain.api.repo.recorder.sys") as fake_sys:
        fake_sys.platform = "linux"
        res = client.post("/v1/recorder/capture/request-permissions", headers=auth_headers)
    assert res.status_code == 501


def test_diagnostics_include_capture_helper(client: TestClient, auth_headers: dict[str, str]):
    with patch("ghostbrain.scheduler.sys") as fake_sys, \
         patch("ghostbrain.recorder.audio.darwin_native.probe", return_value=_DENIED_PROBE) as probe, \
         patch("ghostbrain.recorder.audio.resolve_capture_backend", return_value="blackhole"):
        fake_sys.platform = "darwin"
        res = client.get("/v1/scheduler/diagnostics?refresh=1", headers=auth_headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["platform"] == "darwin"
    assert body["effective_backend"] == "blackhole"
    assert body["capture_helper"]["screen_recording"] == "denied"
    probe.assert_called_once_with(force=True)


def test_diagnostics_off_darwin_have_null_helper(client: TestClient, auth_headers: dict[str, str]):
    with patch("ghostbrain.scheduler.sys") as fake_sys:
        fake_sys.platform = "linux"
        res = client.get("/v1/scheduler/diagnostics", headers=auth_headers)
    body = res.json()
    assert body["capture_helper"] is None
    assert body["effective_backend"] == "unsupported"
