"""NativeBackend (macOS ScreenCaptureKit helper) — subprocess contract tests
against a fake ``ghostbrain-capture`` script, so they run on any POSIX CI."""
from __future__ import annotations

import os
import json
import stat
import sys
import textwrap
import time
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from ghostbrain.recorder.audio import darwin_native, get_backend, resolve_capture_backend
from ghostbrain.recorder.audio.base import CaptureUnavailableError, RouteHandle
from ghostbrain.recorder.audio.darwin import DarwinBackend
from ghostbrain.recorder.audio.darwin_native import NativeBackend, frames_dir_for

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals + shebang")


FAKE_HELPER = textwrap.dedent(
    """\
    #!{python}
    import json, os, signal, struct, sys, time

    argv = sys.argv[1:]
    dump = os.environ.get("FAKE_ARGV_DUMP")
    if dump:
        open(dump, "w").write(json.dumps(argv))

    if argv[:1] == ["--version"]:
        print("ghostbrain-capture 0.0.0-fake"); sys.exit(0)

    if argv[:1] == ["check"]:
        code = int(os.environ.get("FAKE_CHECK_EXIT", "0"))
        payload = json.loads(os.environ.get("FAKE_CHECK_JSON", "{{}}"))
        payload.setdefault("macos", "15.1")
        payload.setdefault("screen_recording", "granted" if code != 4 else "denied")
        payload.setdefault("microphone", "granted" if code != 5 else "denied")
        payload["ok"] = code == 0
        print(json.dumps(payload)); sys.exit(code)

    if argv[:1] == ["request-permissions"]:
        sys.exit(0)

    if argv[:1] != ["run"]:
        sys.exit(2)

    opts = {{}}
    it = iter(argv[1:])
    for a in it:
        opts[a] = next(it, None) if a.startswith("--") else None

    early = os.environ.get("FAKE_EXIT_BEFORE_READY")
    if early:
        print("STARTING version=fake"); sys.stdout.flush(); sys.exit(int(early))
    if os.environ.get("FAKE_NEVER_READY"):
        time.sleep(30); sys.exit(0)

    wav_path = opts["--wav"]
    frames_dir = opts.get("--frames-dir")
    control = opts.get("--control-file")
    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
        json.dump({{"version": 1, "windows": [
            {{"window_id": 77, "app": "us.zoom.xos", "app_name": "zoom.us",
              "title": "Zoom Meeting", "width": 1000, "height": 700, "candidate": True}}]}},
            open(os.path.join(frames_dir, "windows.json"), "w"))
    f = open(wav_path, "wb")
    def header(n):
        return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " +
                struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16) +
                b"data" + struct.pack("<I", n))
    f.write(header(0)); f.flush()

    print("STARTING version=fake pid=%d" % os.getpid())
    if os.environ.get("FAKE_NO_WINDOW"):
        print("TARGET kind=none awaiting_choice=true")
    else:
        print('TARGET kind=window app=us.zoom.xos title="Zoom Meeting"')
    print("READY wav=%s" % wav_path); sys.stdout.flush()

    received = []
    def on_usr(sig, _):
        received.append(sig)
        if frames_dir:
            os.makedirs(frames_dir, exist_ok=True)
            open(os.path.join(frames_dir, "signals.txt"), "a").write("%d\\n" % sig)
    signal.signal(signal.SIGUSR1, on_usr)
    signal.signal(signal.SIGUSR2, on_usr)

    stop = []
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    written = 0
    seen_control = None
    while not stop:
        f.write(b"\\x00" * 3200); written += 3200
        f.seek(0); f.write(header(written)); f.seek(0, 2); f.flush()
        if control and os.path.exists(control) and frames_dir:
            body = open(control).read()
            if body != seen_control:
                seen_control = body
                open(os.path.join(frames_dir, "control.txt"), "a").write(body + "\\n")
        time.sleep(0.05)
    f.close()
    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
        img = os.path.join(frames_dir, "slide-0001-00001200.jpg")
        open(img, "wb").write(b"\\xff\\xd8fake")
        json.dump({{"version": 1, "slides": [
            {{"index": 1, "offset_ms": 1200, "image": "slide-0001-00001200.jpg",
              "text": "Q3 roadmap one two three four five six seven"}}]}},
            open(os.path.join(frames_dir, "slides.json"), "w"))
    print("DONE"); sys.exit(0)
    """
)


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    darwin_native.reset_probe_cache()
    yield
    darwin_native.reset_probe_cache()


@pytest.fixture
def fake_helper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    script = tmp_path / "ghostbrain-capture"
    script.write_text(FAKE_HELPER.format(python=sys.executable), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv(darwin_native.ENV_HELPER_BIN, str(script))
    for var in ("FAKE_CHECK_EXIT", "FAKE_CHECK_JSON", "FAKE_EXIT_BEFORE_READY",
                "FAKE_NEVER_READY", "FAKE_NO_WINDOW", "FAKE_ARGV_DUMP"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(darwin_native, "macos_version", lambda: (15, 1))
    return script


def _wait_exit(pid: int, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not darwin_native.audio_capture.is_running(pid):
            return
        time.sleep(0.05)
    raise AssertionError(f"pid {pid} still alive")


# -- discovery ---------------------------------------------------------------


def test_find_helper_env_wins_over_path(fake_helper: Path, monkeypatch):
    monkeypatch.setattr(darwin_native.shutil, "which", lambda name: "/elsewhere/x")
    assert darwin_native.find_helper() == fake_helper


def test_find_helper_falls_back_to_path(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(darwin_native.ENV_HELPER_BIN, raising=False)
    monkeypatch.setattr(darwin_native.sys, "frozen", False, raising=False)
    exe = tmp_path / "ghostbrain-capture"
    exe.write_text("#!/bin/sh\n")
    monkeypatch.setattr(darwin_native.shutil, "which", lambda name: str(exe))
    assert darwin_native.find_helper() == exe


def test_find_helper_none(tmp_path: Path, monkeypatch):
    monkeypatch.delenv(darwin_native.ENV_HELPER_BIN, raising=False)
    monkeypatch.setattr(darwin_native.shutil, "which", lambda name: None)
    monkeypatch.setattr(darwin_native.Path, "home", classmethod(lambda cls: tmp_path))
    assert darwin_native.find_helper() is None


# -- probe -------------------------------------------------------------------


def test_probe_ok(fake_helper: Path):
    p = darwin_native.probe()
    assert p.found and p.ok and p.code == 0
    assert p.screen_recording == "granted" and p.microphone == "granted"
    assert p.macos_version == "15.1"


@pytest.mark.parametrize("code,needle", [
    (3, "macOS 15+"), (4, "Screen Recording"), (5, "Microphone"),
])
def test_probe_maps_exit_codes(fake_helper: Path, monkeypatch, code, needle):
    monkeypatch.setenv("FAKE_CHECK_EXIT", str(code))
    p = darwin_native.probe()
    assert p.ok is False and p.code == code
    assert needle in p.reason
    ok, missing = NativeBackend().preflight()
    assert ok is False and needle in missing[0]


def test_probe_prefers_issues_from_json(fake_helper: Path, monkeypatch):
    monkeypatch.setenv("FAKE_CHECK_EXIT", "4")
    monkeypatch.setenv("FAKE_CHECK_JSON", '{"issues": ["custom reason from helper"]}')
    assert darwin_native.probe().reason == "custom reason from helper"


def test_probe_is_cached_until_forced(fake_helper: Path, monkeypatch):
    assert darwin_native.probe().ok is True
    monkeypatch.setenv("FAKE_CHECK_EXIT", "4")
    assert darwin_native.probe().ok is True          # cached
    assert darwin_native.probe(force=True).ok is False


def test_probe_not_found(monkeypatch, tmp_path):
    monkeypatch.delenv(darwin_native.ENV_HELPER_BIN, raising=False)
    monkeypatch.setattr(darwin_native.shutil, "which", lambda name: None)
    monkeypatch.setattr(darwin_native.Path, "home", classmethod(lambda cls: tmp_path))
    p = darwin_native.probe()
    assert p.found is False and "not found" in p.reason


# -- backend selection -------------------------------------------------------


def test_resolve_explicit_values_win(fake_helper: Path, monkeypatch):
    monkeypatch.setenv("FAKE_CHECK_EXIT", "4")
    assert resolve_capture_backend({"capture_backend": "native"}) == "native"
    assert resolve_capture_backend({"capture_backend": "blackhole"}) == "blackhole"


def test_resolve_auto_follows_probe(fake_helper: Path, monkeypatch):
    assert resolve_capture_backend({"capture_backend": "auto"}) == "native"
    darwin_native.reset_probe_cache()
    monkeypatch.setenv("FAKE_CHECK_EXIT", "4")
    assert resolve_capture_backend({}) == "blackhole"


def test_get_backend_darwin_native(fake_helper: Path):
    backend = get_backend("darwin", recorder_cfg={
        "capture_backend": "auto", "capture_slides": False, "slide_fps": 2,
        "slide_fallback": "display",
    })
    assert isinstance(backend, NativeBackend)
    assert backend.name == "native"
    assert backend.capture_slides is False
    assert backend.slide_fps == 2
    assert backend.slide_fallback == "display"


def test_get_backend_darwin_blackhole_carries_reason(fake_helper: Path, monkeypatch):
    monkeypatch.setenv("FAKE_CHECK_EXIT", "4")
    backend = get_backend("darwin", recorder_cfg={"capture_backend": "auto"})
    assert isinstance(backend, DarwinBackend)
    assert "Screen Recording" in backend.native_fallback_reason
    with patch("ghostbrain.recorder.audio.darwin.shutil.which", return_value=None):
        ok, missing = backend.preflight()
    assert ok is False and "native capture unavailable" in missing[0]


# -- routing -----------------------------------------------------------------


def test_native_route_is_noop():
    handle = NativeBackend().begin_meeting_route("Ghost Brain", "")
    assert handle == RouteHandle(previous_output="", switched=False)


def test_native_end_route_restores_legacy_switch():
    """Upgrade path: an in-flight ffmpeg recording stashed the previous output
    device; the native backend must still restore it."""
    with patch("ghostbrain.recorder.audio_switcher.switch_to") as sw:
        NativeBackend().end_meeting_route(RouteHandle("Speakers", switched=True))
        sw.assert_called_once_with("Speakers")
        sw.reset_mock()
        NativeBackend().end_meeting_route(RouteHandle("", switched=False))
        sw.assert_not_called()


# -- capture lifecycle -------------------------------------------------------


def test_start_stop_roundtrip_writes_wav_and_slides(fake_helper: Path, tmp_path: Path):
    wav = tmp_path / "rec" / "meeting-x.wav"
    backend = NativeBackend(capture_slides=True, slide_fps=1)
    handle = backend.start_capture(wav, log_path=tmp_path / "capture.log")
    try:
        assert handle.pid > 0
        assert handle.awaiting_target_choice is False
        assert backend.capture_alive(handle.pid)
        time.sleep(0.3)
    finally:
        assert backend.stop_capture(handle.pid) is True
    _wait_exit(handle.pid)
    with wave.open(str(wav), "rb") as f:
        assert f.getframerate() == 16000 and f.getnframes() > 0
    assert (frames_dir_for(wav) / "slides.json").exists()
    assert (tmp_path / "capture.log").exists()


def test_start_records_argv_contract(fake_helper: Path, tmp_path: Path, monkeypatch):
    dump = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_ARGV_DUMP", str(dump))
    wav = tmp_path / "m.wav"
    backend = NativeBackend(capture_slides=True, slide_fps=2, slide_fallback="audio")
    handle = backend.start_capture(wav)
    backend.stop_capture(handle.pid)
    import json
    argv = json.loads(dump.read_text())
    assert argv[0] == "run"
    assert argv[argv.index("--wav") + 1] == str(wav)
    assert argv[argv.index("--frames-dir") + 1] == str(frames_dir_for(wav))
    assert argv[argv.index("--control-file") + 1] == str(darwin_native.control_file_for(wav))
    assert argv[argv.index("--fps") + 1] == "2"
    assert argv[argv.index("--no-window-policy") + 1] == "audio"
    assert argv[argv.index("--target") + 1] == "auto"


def test_start_without_slides_omits_frames_dir(fake_helper: Path, tmp_path: Path, monkeypatch):
    dump = tmp_path / "argv.json"
    monkeypatch.setenv("FAKE_ARGV_DUMP", str(dump))
    backend = NativeBackend(capture_slides=False)
    handle = backend.start_capture(tmp_path / "m.wav")
    backend.stop_capture(handle.pid)
    import json
    argv = json.loads(dump.read_text())
    assert "--frames-dir" not in argv and "--fps" not in argv and "--control-file" not in argv


def test_control_file_roundtrip_and_window_catalog(fake_helper: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FAKE_NO_WINDOW", "1")
    wav = tmp_path / "m.wav"
    backend = NativeBackend()
    handle = backend.start_capture(wav)
    try:
        assert handle.awaiting_target_choice is True
        time.sleep(0.2)
        assert darwin_native.list_windows(wav) == [{
            "windowId": 77, "app": "us.zoom.xos", "appName": "zoom.us", "title": "Zoom Meeting",
            "width": 1000, "height": 700, "candidate": True,
        }]
        darwin_native.write_control(wav, "window", 77)
        time.sleep(0.2)
        darwin_native.write_control(wav, "audio")
        time.sleep(0.2)
        with pytest.raises(ValueError):
            darwin_native.write_control(wav, "window")
        with pytest.raises(ValueError):
            darwin_native.write_control(wav, "bogus")
    finally:
        backend.stop_capture(handle.pid)
    _wait_exit(handle.pid)
    seen = (frames_dir_for(wav) / "control.txt").read_text().splitlines()
    assert [json.loads(x) for x in seen] == [
        {"target": "window", "window_id": 77}, {"target": "audio"},
    ]
    assert darwin_native.control_file_for(wav).exists()
    from ghostbrain.recorder import slides
    slides.cleanup_frames(wav)
    assert not darwin_native.control_file_for(wav).exists()
    assert darwin_native.list_windows(wav) == []


def test_start_reports_awaiting_choice_and_signals(fake_helper: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FAKE_NO_WINDOW", "1")
    wav = tmp_path / "m.wav"
    backend = NativeBackend()
    handle = backend.start_capture(wav)
    try:
        assert handle.awaiting_target_choice is True
        assert darwin_native.enable_display_capture(handle.pid) is True
        time.sleep(0.2)
        assert darwin_native.decline_display_capture(handle.pid) is True
        time.sleep(0.2)
    finally:
        backend.stop_capture(handle.pid)
    _wait_exit(handle.pid)
    sigs = (frames_dir_for(wav) / "signals.txt").read_text().split()
    import signal as _s
    assert sigs == [str(int(_s.SIGUSR1)), str(int(_s.SIGUSR2))]
    assert darwin_native.enable_display_capture(handle.pid) is False  # dead pid


@pytest.mark.parametrize("code", [3, 4, 5])
def test_start_precondition_exit_raises_unavailable(fake_helper: Path, tmp_path: Path, monkeypatch, code):
    monkeypatch.setenv("FAKE_EXIT_BEFORE_READY", str(code))
    with pytest.raises(CaptureUnavailableError):
        NativeBackend().start_capture(tmp_path / "m.wav")


def test_start_other_exit_raises_runtime(fake_helper: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FAKE_EXIT_BEFORE_READY", "6")
    with pytest.raises(RuntimeError, match="code 6"):
        NativeBackend().start_capture(tmp_path / "m.wav")


def test_start_ready_timeout_kills_helper(fake_helper: Path, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FAKE_NEVER_READY", "1")
    backend = NativeBackend(ready_timeout_s=0.5)
    with pytest.raises(RuntimeError, match="READY"):
        backend.start_capture(tmp_path / "m.wav")


def test_start_without_helper_raises_unavailable(monkeypatch, tmp_path):
    monkeypatch.delenv(darwin_native.ENV_HELPER_BIN, raising=False)
    monkeypatch.setattr(darwin_native.shutil, "which", lambda name: None)
    monkeypatch.setattr(darwin_native.Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(CaptureUnavailableError, match="not found"):
        NativeBackend().start_capture(tmp_path / "m.wav")


def test_request_permissions_reprobes(fake_helper: Path, monkeypatch):
    monkeypatch.setenv("FAKE_CHECK_EXIT", "4")
    assert darwin_native.probe().ok is False
    monkeypatch.setenv("FAKE_CHECK_EXIT", "0")
    assert darwin_native.request_permissions().ok is True


def test_parse_kv_line():
    key, fields = darwin_native._parse_kv_line(
        'TARGET kind=window app=com.microsoft.teams2 title="Weekly | Teams" window_id=8'
    )
    assert key == "TARGET"
    assert fields == {"kind": "window", "app": "com.microsoft.teams2",
                      "title": "Weekly | Teams", "window_id": "8"}
    assert darwin_native._parse_kv_line("DONE") == ("DONE", {})


def test_frames_dir_for():
    assert frames_dir_for(Path("/x/meeting-1.wav")) == Path("/x/meeting-1.frames")
    assert os.path.basename(str(frames_dir_for(Path("a.b.wav")))) == "a.b.frames"
