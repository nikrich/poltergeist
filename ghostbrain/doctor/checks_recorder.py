"""Recorder dependency checks.

macOS needs: ffmpeg (capture), whisper-cli + a ggml model (transcription),
SwitchAudioSource (routing), BlackHole 2ch (virtual output), and a multi-output
device named per `recorder.audio_device` so system audio reaches BlackHole
while the user still hears it. Windows uses the WASAPI backend's own preflight.
"""
from __future__ import annotations

import shutil
import sys

from ghostbrain.doctor import CheckResult, Fix, register

IDS = (
    "ffmpeg", "whisper-cli", "whisper-model", "switchaudio",
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


def _skip(check_id: str) -> CheckResult:
    return CheckResult(id=check_id, status="skip", summary="not applicable on this platform")


def _mac_only(check_id: str) -> CheckResult | None:
    return None if _platform() == "darwin" else _skip(check_id)


@register("ffmpeg")
def check_ffmpeg() -> CheckResult:
    if (s := _mac_only("ffmpeg")) is not None:
        return s
    path = shutil.which("ffmpeg")
    if path:
        return CheckResult(id="ffmpeg", status="ok", summary=path)
    return CheckResult(
        id="ffmpeg", status="fail", summary="ffmpeg not found on PATH",
        detail="ffmpeg captures BlackHole + microphone into the meeting WAV.",
        fix=Fix(kind="automated", command="setup deps --only ffmpeg"),
    )


@register("whisper-cli")
def check_whisper_cli() -> CheckResult:
    if (s := _mac_only("whisper-cli")) is not None:
        return s
    path = shutil.which("whisper-cli")
    if path:
        return CheckResult(id="whisper-cli", status="ok", summary=path)
    return CheckResult(
        id="whisper-cli", status="fail", summary="whisper-cli not found on PATH",
        detail="whisper.cpp's CLI transcribes recordings locally.",
        fix=Fix(kind="automated", command="setup deps --only whisper-cpp"),
    )


@register("whisper-model")
def check_whisper_model() -> CheckResult:
    if (s := _mac_only("whisper-model")) is not None:
        return s
    from ghostbrain.recorder.transcribe import DEFAULT_MODEL_DIR, TranscribeError, _resolve_model

    try:
        model = _resolve_model(None)
    except TranscribeError as e:
        return CheckResult(
            id="whisper-model", status="fail",
            summary=f"no ggml-*.bin in {DEFAULT_MODEL_DIR}",
            detail=str(e),
            fix=Fix(kind="automated", command="setup fetch-model",
                    note="downloads ggml-medium.en.bin (~1.5 GB); pass base.en or small.en for a smaller model"),
        )
    return CheckResult(id="whisper-model", status="ok", summary=model.name, data={"model": str(model)})


@register("switchaudio")
def check_switchaudio() -> CheckResult:
    if (s := _mac_only("switchaudio")) is not None:
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
    if (s := _mac_only("blackhole")) is not None:
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
    if (s := _mac_only("audio-device")) is not None:
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
    if (s := _mac_only("audio-routing")) is not None:
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
