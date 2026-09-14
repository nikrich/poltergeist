"""Recorder dependency checks.

macOS records meetings one of two ways (`recorder.capture_backend:
auto|native|blackhole`, see `ghostbrain/recorder/config.py`): the bundled
ScreenCaptureKit helper (`native`, macOS 15+, needs Screen Recording +
Microphone permission, no other dependencies), or the legacy ffmpeg +
BlackHole + SwitchAudioSource + multi-output-device path (`blackhole`).
`auto` (the default) picks native when it is ready, else falls back to
blackhole. The `capture-method` check reports which one is in effect; the
five checks below it (ffmpeg, whisper-cli/whisper-model excepted) only run
when the BlackHole path is actually needed. Windows uses the WASAPI
backend's own preflight.
"""
from __future__ import annotations

import shutil
import sys

from ghostbrain.doctor import CheckResult, Fix, register

IDS = (
    "capture-method", "ffmpeg", "whisper-cli", "whisper-model", "switchaudio",
    "blackhole", "audio-device", "audio-routing", "recorder-backend",
)

BLACKHOLE_DEVICE = "BlackHole 2ch"


def _platform() -> str:
    return sys.platform


def _backend():
    from ghostbrain.recorder.audio import get_backend

    return get_backend()


def _configured_device() -> str:
    from ghostbrain.recorder.daemon import DaemonConfig

    return DaemonConfig.load().audio_device


def _effective_method() -> str:
    """``"native"`` or ``"blackhole"`` — what capture will actually use."""
    from ghostbrain.recorder.audio import resolve_capture_backend

    return resolve_capture_backend()


def _configured_method() -> str:
    """``"auto"``, ``"native"``, or ``"blackhole"`` — what the config says."""
    from ghostbrain.recorder.config import capture_backend_from, load_recorder_block

    return capture_backend_from(load_recorder_block())


def _probe_native():
    from ghostbrain.recorder.audio import darwin_native

    return darwin_native.probe()


def _skip(check_id: str) -> CheckResult:
    return CheckResult(id=check_id, status="skip", summary="not applicable on this platform")


def _mac_only(check_id: str) -> CheckResult | None:
    return None if _platform() == "darwin" else _skip(check_id)


def _mac_or_windows(check_id: str) -> CheckResult | None:
    return None if _platform() in ("darwin", "win32") else _skip(check_id)


def _blackhole_only(check_id: str) -> CheckResult | None:
    """Like :func:`_mac_only`, plus a skip on macOS when native capture is
    the effective method — the BlackHole-path checks don't apply then."""
    if _platform() != "darwin":
        return _skip(check_id)
    if _effective_method() == "native":
        return CheckResult(id=check_id, status="skip", summary="not needed with native capture")
    return None


def _native_capture_fix(probe) -> Fix:
    if not probe.found:
        return Fix(
            kind="manual",
            command=("the packaged app bundles the helper; from a source checkout run "
                     "scripts/build-native-macos.sh --install, then re-run doctor"),
        )
    if not probe.macos_supported:
        return Fix(
            kind="manual",
            command=("native capture needs macOS 15+; use the BlackHole path "
                     "(set recorder.capture_backend: blackhole) or upgrade macOS"),
        )
    return Fix(
        kind="manual",
        command="Settings → meetings → diagnostics → grant access (Screen Recording + Microphone), then re-check",
        note=("macOS lists an app under Screen Recording only after it has attempted "
              "capture; grant from the app, not from Terminal"),
    )


@register("capture-method")
def check_capture_method() -> CheckResult:
    if (s := _mac_only("capture-method")) is not None:
        return s

    effective = _effective_method()
    configured = _configured_method()
    probe = None

    def get_probe():
        nonlocal probe
        if probe is None:
            probe = _probe_native()
        return probe

    if configured == "native":
        p = get_probe()
        if not p.ok:
            return CheckResult(
                id="capture-method", status="fail",
                summary=f"native capture not ready: {p.reason}",
                detail=("recorder.capture_backend is set to native, but the "
                         "ScreenCaptureKit helper isn't ready to capture."),
                fix=_native_capture_fix(p),
                data={"method": effective, "configured": configured, "probe": p.to_dict()},
            )

    if effective == "native":
        p = get_probe()
        return CheckResult(
            id="capture-method", status="ok",
            summary=f"native — ScreenCaptureKit helper at {p.path}",
            data={"method": "native", "configured": configured},
        )

    if configured == "blackhole":
        return CheckResult(
            id="capture-method", status="ok",
            summary="blackhole (configured) — ffmpeg + BlackHole path",
            data={"method": "blackhole", "configured": "blackhole"},
        )

    p = get_probe()
    return CheckResult(
        id="capture-method", status="warn",
        summary=f"blackhole fallback — native helper unavailable: {p.reason}",
        detail=("Native capture (ScreenCaptureKit) needs no ffmpeg, BlackHole, "
                 "SwitchAudioSource, or multi-output device — once it's ready "
                 "doctor will pick it up automatically."),
        fix=_native_capture_fix(p),
        data={"method": effective, "configured": configured, "probe": p.to_dict()},
    )


@register("ffmpeg")
def check_ffmpeg() -> CheckResult:
    if (s := _blackhole_only("ffmpeg")) is not None:
        return s
    # Reuse the backend's own preflight (same seam check_recorder_backend
    # uses on Windows) instead of a second, separately-maintained PATH check.
    ok, missing = _backend().preflight()
    if not ok:
        summary = missing[0] if missing else "ffmpeg not found on PATH"
        return CheckResult(
            id="ffmpeg", status="fail", summary=summary,
            detail="ffmpeg captures BlackHole + microphone into the meeting WAV.",
            fix=Fix(kind="automated", command="setup deps --only ffmpeg"),
        )
    path = shutil.which("ffmpeg")
    return CheckResult(id="ffmpeg", status="ok", summary=path or "ffmpeg")


@register("whisper-cli")
def check_whisper_cli() -> CheckResult:
    if (s := _mac_or_windows("whisper-cli")) is not None:
        return s
    path = shutil.which("whisper-cli")
    if path:
        return CheckResult(id="whisper-cli", status="ok", summary=path)
    fix = (
        Fix(kind="automated", command="setup deps --only whisper-cpp")
        if _platform() == "darwin"
        else Fix(kind="manual", command="install whisper.cpp and add whisper-cli to PATH — see docs/install/windows.md")
    )
    return CheckResult(
        id="whisper-cli", status="fail", summary="whisper-cli not found on PATH",
        detail="whisper.cpp's CLI transcribes recordings locally.",
        fix=fix,
    )


@register("whisper-model")
def check_whisper_model() -> CheckResult:
    if (s := _mac_or_windows("whisper-model")) is not None:
        return s
    from ghostbrain.recorder.transcribe import DEFAULT_MODEL_DIR, TranscribeError, _resolve_model

    try:
        model = _resolve_model(None)
    except TranscribeError as e:
        fix = (
            Fix(kind="automated", command="setup fetch-model",
                note="downloads ggml-medium.en.bin (~1.5 GB); pass base.en or small.en for a smaller model")
            if _platform() == "darwin"
            else Fix(kind="manual", command="download a ggml-*.bin into ~/ghostbrain/recorder/models/ by hand — see docs/install/windows.md")
        )
        return CheckResult(
            id="whisper-model", status="fail",
            summary=f"no ggml-*.bin in {DEFAULT_MODEL_DIR}",
            detail=str(e),
            fix=fix,
        )
    return CheckResult(id="whisper-model", status="ok", summary=model.name, data={"model": str(model)})


@register("switchaudio")
def check_switchaudio() -> CheckResult:
    if (s := _blackhole_only("switchaudio")) is not None:
        return s
    path = shutil.which("SwitchAudioSource")
    if path:
        return CheckResult(id="switchaudio", status="ok", summary=path)
    return CheckResult(
        id="switchaudio", status="fail", summary="SwitchAudioSource not found on PATH",
        detail="Used to flip macOS output to the multi-output device for the meeting and back after.",
        fix=Fix(kind="automated", command="setup deps --only switchaudio-osx"),
    )


def _outputs() -> list[str] | None:
    """None when SwitchAudioSource is unavailable (dependent checks skip)."""
    if shutil.which("SwitchAudioSource") is None:
        return None
    from ghostbrain.recorder import audio_switcher

    try:
        return audio_switcher.list_outputs()
    except audio_switcher.AudioSwitcherError:
        return None


@register("blackhole")
def check_blackhole() -> CheckResult:
    if (s := _blackhole_only("blackhole")) is not None:
        return s
    outputs = _outputs()
    if outputs is None:
        return CheckResult(id="blackhole", status="skip", summary="needs SwitchAudioSource first")
    if BLACKHOLE_DEVICE in outputs:
        return CheckResult(id="blackhole", status="ok", summary=BLACKHOLE_DEVICE)
    return CheckResult(
        id="blackhole", status="fail", summary=f"{BLACKHOLE_DEVICE} not installed",
        detail="Virtual output that lets ffmpeg capture what the meeting app plays.",
        fix=Fix(kind="interactive", command="setup deps --only blackhole",
                note="the installer asks for your macOS password, so run this one in Terminal"),
    )


@register("audio-device")
def check_audio_device() -> CheckResult:
    if (s := _blackhole_only("audio-device")) is not None:
        return s
    outputs = _outputs()
    if outputs is None:
        return CheckResult(id="audio-device", status="skip", summary="needs SwitchAudioSource first")
    name = _configured_device()
    if name in outputs:
        return CheckResult(id="audio-device", status="ok", summary=name, data={"device": name})
    return CheckResult(
        id="audio-device", status="fail", summary=f"no output device named '{name}'",
        detail="A multi-output device (speakers + BlackHole) so you hear the meeting while it is captured.",
        fix=Fix(kind="automated", command="setup audio-device"),
        data={"device": name},
    )


@register("audio-routing")
def check_audio_routing() -> CheckResult:
    if (s := _blackhole_only("audio-routing")) is not None:
        return s
    if shutil.which("SwitchAudioSource") is None:
        return CheckResult(id="audio-routing", status="skip", summary="needs SwitchAudioSource first")
    from ghostbrain.recorder import audio_switcher

    name = _configured_device()
    try:
        current = audio_switcher.current_output()
    except audio_switcher.AudioSwitcherError as e:
        return CheckResult(id="audio-routing", status="warn", summary=f"could not read output: {e}")
    if current == name:
        return CheckResult(id="audio-routing", status="ok", summary=current)
    return CheckResult(
        id="audio-routing", status="warn", summary=f"output is '{current}', not '{name}'",
        detail="Calendar recordings switch this automatically; the manual Record button needs it set first.",
        fix=Fix(kind="manual", command=f"Sound menu → Output → {name}"),
    )


@register("recorder-backend")
def check_recorder_backend() -> CheckResult:
    if _platform() != "win32":
        return _skip("recorder-backend")
    ok, missing = _backend().preflight()
    if ok:
        return CheckResult(id="recorder-backend", status="ok", summary="WASAPI backend ready")
    return CheckResult(
        id="recorder-backend", status="fail", summary="recorder prerequisites missing",
        detail="\n".join(missing),
        fix=Fix(kind="manual", command="follow docs/install/windows.md (dependencies section)"),
    )
