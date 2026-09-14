from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.doctor import checks_recorder as cr
from ghostbrain.recorder import audio_switcher
from ghostbrain.recorder.audio import darwin_native


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(cr, "_platform", lambda: "darwin")


@pytest.fixture(autouse=True)
def default_capture_method(monkeypatch):
    # Every existing test in this module predates capture_backend gating and
    # assumes the BlackHole path is active — keep that meaning unless a test
    # overrides these seams itself.
    monkeypatch.setattr(cr, "_effective_method", lambda: "blackhole")
    monkeypatch.setattr(cr, "_configured_method", lambda: "blackhole")


def _which(present: set[str]):
    return lambda name: f"/opt/homebrew/bin/{name}" if name in present else None


class _FakeBackend:
    def __init__(self, ok: bool, missing: list[str]):
        self._ok = ok
        self._missing = missing

    def preflight(self):
        return self._ok, self._missing


def test_ffmpeg_missing_is_automated_fix(darwin, monkeypatch):
    monkeypatch.setattr(cr, "_backend",
                        lambda: _FakeBackend(False, ["ffmpeg not on PATH (install via Homebrew: brew install ffmpeg)"]))
    r = cr.check_ffmpeg()
    assert r.status == "fail"
    assert "ffmpeg not on PATH" in r.summary
    assert r.fix.kind == "automated"
    assert r.fix.command == "setup deps --only ffmpeg"


def test_ffmpeg_present_ok(darwin, monkeypatch):
    monkeypatch.setattr(cr, "_backend", lambda: _FakeBackend(True, []))
    monkeypatch.setattr(cr.shutil, "which", _which({"ffmpeg"}))
    assert cr.check_ffmpeg().status == "ok"


def test_whisper_cli_missing(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which(set()))
    r = cr.check_whisper_cli()
    assert r.status == "fail"
    assert r.fix.command == "setup deps --only whisper-cpp"


def test_whisper_model_missing_and_present(darwin, monkeypatch, tmp_path: Path):
    from ghostbrain.recorder import transcribe

    monkeypatch.setattr(transcribe, "DEFAULT_MODEL_DIR", tmp_path)
    monkeypatch.delenv("GHOSTBRAIN_WHISPER_MODEL", raising=False)
    r = cr.check_whisper_model()
    assert r.status == "fail"
    assert r.fix.command == "setup fetch-model"
    (tmp_path / "ggml-small.en.bin").write_bytes(b"x" * 10)
    r = cr.check_whisper_model()
    assert r.status == "ok"
    assert r.data["model"].endswith("ggml-small.en.bin")


def test_blackhole_and_audio_device(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which({"SwitchAudioSource"}))
    monkeypatch.setattr(audio_switcher, "list_outputs", lambda: ["MacBook Pro Speakers"])
    monkeypatch.setattr(cr, "_configured_device", lambda: "Ghost Brain")
    assert cr.check_blackhole().status == "fail"
    assert cr.check_blackhole().fix.kind == "interactive"
    assert cr.check_audio_device().status == "fail"
    assert cr.check_audio_device().fix.command == "setup audio-device"

    monkeypatch.setattr(
        audio_switcher, "list_outputs",
        lambda: ["BlackHole 2ch", "MacBook Pro Speakers", "Ghost Brain"],
    )
    assert cr.check_blackhole().status == "ok"
    assert cr.check_audio_device().status == "ok"


def test_audio_routing_is_warn_only(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which({"SwitchAudioSource"}))
    monkeypatch.setattr(cr, "_configured_device", lambda: "Ghost Brain")
    monkeypatch.setattr(audio_switcher, "current_output", lambda: "MacBook Pro Speakers")
    r = cr.check_audio_routing()
    assert r.status == "warn"
    assert r.fix.kind == "manual"
    monkeypatch.setattr(audio_switcher, "current_output", lambda: "Ghost Brain")
    assert cr.check_audio_routing().status == "ok"


def test_switchaudio_missing_makes_dependent_checks_skip(darwin, monkeypatch):
    monkeypatch.setattr(cr.shutil, "which", _which(set()))
    assert cr.check_switchaudio().status == "fail"
    assert cr.check_blackhole().status == "skip"
    assert cr.check_audio_device().status == "skip"
    assert cr.check_audio_routing().status == "skip"


def test_whisper_checks_run_on_windows_with_manual_fixes(monkeypatch, tmp_path: Path):
    from ghostbrain.recorder import transcribe

    monkeypatch.setattr(cr, "_platform", lambda: "win32")
    monkeypatch.setattr(cr.shutil, "which", _which(set()))
    monkeypatch.setattr(transcribe, "DEFAULT_MODEL_DIR", tmp_path)
    monkeypatch.delenv("GHOSTBRAIN_WHISPER_MODEL", raising=False)
    cli = cr.check_whisper_cli()
    assert cli.status == "fail"
    assert cli.fix.kind == "manual"
    assert "docs/install/windows.md" in cli.fix.command
    model = cr.check_whisper_model()
    assert model.status == "fail"
    assert model.fix.kind == "manual"
    assert "docs/install/windows.md" in model.fix.command


def test_whisper_checks_still_skip_on_linux(monkeypatch):
    monkeypatch.setattr(cr, "_platform", lambda: "linux")
    assert cr.check_whisper_cli().status == "skip"
    assert cr.check_whisper_model().status == "skip"


def test_mac_only_checks_skip_on_linux(monkeypatch):
    monkeypatch.setattr(cr, "_platform", lambda: "linux")
    for fn in (cr.check_capture_method, cr.check_ffmpeg, cr.check_whisper_cli,
               cr.check_whisper_model, cr.check_switchaudio, cr.check_blackhole,
               cr.check_audio_device, cr.check_audio_routing):
        assert fn().status == "skip", fn.__name__


def test_native_effective_method_skips_blackhole_path_checks(darwin, monkeypatch):
    monkeypatch.setattr(cr, "_effective_method", lambda: "native")
    for fn in (cr.check_ffmpeg, cr.check_switchaudio, cr.check_blackhole,
               cr.check_audio_device, cr.check_audio_routing):
        r = fn()
        assert r.status == "skip", fn.__name__
        assert r.summary == "not needed with native capture", fn.__name__


def test_capture_method_ok_native(darwin, monkeypatch):
    monkeypatch.setattr(cr, "_effective_method", lambda: "native")
    monkeypatch.setattr(cr, "_configured_method", lambda: "auto")
    probe = darwin_native.HelperProbe(
        found=True, path="/usr/local/bin/ghostbrain-capture", ok=True, code=0,
        reason="ok", macos_version="15.1", macos_supported=True,
        screen_recording="granted", microphone="granted",
    )
    monkeypatch.setattr(cr, "_probe_native", lambda: probe)
    r = cr.check_capture_method()
    assert r.status == "ok"
    assert r.summary == f"native — ScreenCaptureKit helper at {probe.path}"
    assert r.data == {"method": "native", "configured": "auto"}


def test_capture_method_ok_blackhole_configured(darwin, monkeypatch):
    monkeypatch.setattr(cr, "_effective_method", lambda: "blackhole")
    monkeypatch.setattr(cr, "_configured_method", lambda: "blackhole")

    def _boom():
        raise AssertionError("probe should not be called when blackhole is configured")

    monkeypatch.setattr(cr, "_probe_native", _boom)
    r = cr.check_capture_method()
    assert r.status == "ok"
    assert r.summary == "blackhole (configured) — ffmpeg + BlackHole path"
    assert r.data == {"method": "blackhole", "configured": "blackhole"}


def test_capture_method_warn_auto_fallback(darwin, monkeypatch):
    monkeypatch.setattr(cr, "_effective_method", lambda: "blackhole")
    monkeypatch.setattr(cr, "_configured_method", lambda: "auto")
    probe = darwin_native.HelperProbe(
        found=False, path=None, ok=False, code=None,
        reason=("ghostbrain-capture not found; set GHOSTBRAIN_CAPTURE_BIN or run "
                "scripts/build-native-macos.sh --install"),
        macos_version="15.1", macos_supported=True,
    )
    monkeypatch.setattr(cr, "_probe_native", lambda: probe)
    r = cr.check_capture_method()
    assert r.status == "warn"
    assert r.summary == f"blackhole fallback — native helper unavailable: {probe.reason}"
    assert r.fix.kind == "manual"
    assert "build-native-macos.sh --install" in r.fix.command
    assert r.data["probe"] == probe.to_dict()
    assert r.data["method"] == "blackhole"
    assert r.data["configured"] == "auto"


def test_capture_method_fail_native_configured_not_ready(darwin, monkeypatch):
    monkeypatch.setattr(cr, "_effective_method", lambda: "native")
    monkeypatch.setattr(cr, "_configured_method", lambda: "native")
    probe = darwin_native.HelperProbe(
        found=True, path="/usr/local/bin/ghostbrain-capture", ok=False, code=5,
        reason=("Microphone permission not granted — System Settings › Privacy "
                "& Security › Microphone"),
        macos_version="15.1", macos_supported=True,
        screen_recording="granted", microphone="denied",
    )
    monkeypatch.setattr(cr, "_probe_native", lambda: probe)
    r = cr.check_capture_method()
    assert r.status == "fail"
    assert r.summary == f"native capture not ready: {probe.reason}"
    assert r.fix.kind == "manual"
    assert "grant access" in r.fix.command


def test_recorder_backend_check_surfaces_preflight_on_windows(monkeypatch):
    monkeypatch.setattr(cr, "_platform", lambda: "win32")

    class FakeBackend:
        def preflight(self):
            return False, ["sounddevice not installed"]

    monkeypatch.setattr(cr, "_backend", lambda: FakeBackend())
    r = cr.check_recorder_backend()
    assert r.status == "fail"
    assert "sounddevice" in r.detail
    assert r.fix.kind == "manual"
    assert "docs/install/windows.md" in r.fix.command


def test_registration_order():
    from ghostbrain import doctor

    ids = [i for i, _ in doctor.CHECKS]
    rec = [i for i in ids if i in cr.IDS]
    assert rec == list(cr.IDS)
