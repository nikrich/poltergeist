"""macOS native backend: the ``ghostbrain-capture`` ScreenCaptureKit helper.

One helper process captures system audio + microphone (mixed to the same
16 kHz mono WAV the transcriber expects) and, optionally, low-fps screen
frames of the meeting-app window that are deduplicated + OCR'd into
``<wav>.frames/slides.json``. No BlackHole, no SwitchAudioSource, no ffmpeg.

The helper is a separate binary (see ``native/macos/ghostbrain-capture/``)
because ScreenCaptureKit is only reachable from native code. Python talks to
it the same way it talked to ffmpeg: spawn in its own session, persist the
pid, SIGINT to stop. The "no meeting window found" prompt is answered through
a small JSON control file the helper polls once a second
(``{"target": "display" | "audio" | "window", "window_id": N}``); while it
waits it also writes ``<frames>/windows.json`` listing the windows a user may
pick. SIGUSR1/SIGUSR2 remain as signal shortcuts for display / audio-only.

CLI contract (canonical copy in the helper README):

    ghostbrain-capture run --wav <p> [--frames-dir <d>] [--control-file <f>] [--fps N]
                           [--target auto|display|window]
                           [--no-window-policy ask|display|audio]
    ghostbrain-capture check [--json] [--audio-only]
    ghostbrain-capture request-permissions

Exit codes: 0 ok · 1 internal · 2 usage · 3 macOS < 15 · 4 Screen Recording
denied · 5 Microphone denied · 6 stream failed to start · 7 output I/O ·
8 no display · 9 stream stopped unexpectedly.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from ghostbrain.recorder import audio_capture
from ghostbrain.recorder.audio.base import CaptureUnavailableError, RouteHandle
from ghostbrain.recorder.audio_capture import CaptureHandle

log = logging.getLogger("ghostbrain.recorder.audio.darwin_native")

HELPER_NAME = "ghostbrain-capture"
ENV_HELPER_BIN = "GHOSTBRAIN_CAPTURE_BIN"
MIN_MACOS_MAJOR = 15

EXIT_OK = 0
EXIT_INTERNAL = 1
EXIT_USAGE = 2
EXIT_MACOS_TOO_OLD = 3
EXIT_SCREEN_DENIED = 4
EXIT_MIC_DENIED = 5
EXIT_STREAM_START = 6
EXIT_OUTPUT_IO = 7
EXIT_NO_DISPLAY = 8
EXIT_STREAM_STOPPED = 9

_PRECONDITION_CODES = {EXIT_MACOS_TOO_OLD, EXIT_SCREEN_DENIED, EXIT_MIC_DENIED}

READY_TIMEOUT_S = 20.0
PROBE_TIMEOUT_S = 10.0
PROBE_TTL_S = 60.0
REQUEST_PERMISSIONS_TIMEOUT_S = 60.0
STOP_GRACE_S = 10.0

SCREEN_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
)
MIC_SETTINGS_URL = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone"
)


# ---------------------------------------------------------------------------
# Discovery + probing
# ---------------------------------------------------------------------------


def find_helper() -> Path | None:
    """``GHOSTBRAIN_CAPTURE_BIN`` → bundled sibling (frozen sidecar) → PATH."""
    env = os.environ.get(ENV_HELPER_BIN, "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
        log.warning("%s=%s does not exist", ENV_HELPER_BIN, env)
    if getattr(sys, "frozen", False):
        # PyInstaller onedir lives at Resources/sidecar/ghostbrain-api/<exe>;
        # electron-builder drops the helper at Resources/bin/<helper>.
        try:
            candidate = Path(sys.executable).resolve().parents[2] / "bin" / HELPER_NAME
            if candidate.is_file():
                return candidate
        except IndexError:
            pass
    which = shutil.which(HELPER_NAME)
    if which:
        return Path(which)
    for fallback in (Path.home() / ".local" / "bin" / HELPER_NAME,):
        if fallback.is_file():
            return fallback
    return None


def macos_version() -> tuple[int, int]:
    raw = platform.mac_ver()[0] or ""
    parts = raw.split(".")
    try:
        major = int(parts[0]) if parts and parts[0] else 0
        minor = int(parts[1]) if len(parts) > 1 and parts[1] else 0
    except ValueError:
        return (0, 0)
    return (major, minor)


def macos_supported() -> bool:
    major, _ = macos_version()
    return major >= MIN_MACOS_MAJOR


@dataclasses.dataclass
class HelperProbe:
    found: bool
    path: str | None
    ok: bool
    code: int | None
    reason: str
    macos_version: str
    macos_supported: bool
    screen_recording: str = "unknown"   # granted | denied | not_determined | unknown
    microphone: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _reason_for_code(code: int | None) -> str:
    if code == EXIT_OK:
        return "ok"
    if code == EXIT_MACOS_TOO_OLD:
        major, minor = macos_version()
        return (f"macOS {MIN_MACOS_MAJOR}+ required for native capture (found "
                f"{major}.{minor}); set recorder.capture_backend: blackhole")
    if code == EXIT_SCREEN_DENIED:
        return ("Screen Recording permission not granted — System Settings › Privacy "
                "& Security › Screen & System Audio Recording")
    if code == EXIT_MIC_DENIED:
        return ("Microphone permission not granted — System Settings › Privacy "
                "& Security › Microphone")
    if code == EXIT_USAGE:
        return "ghostbrain-capture rejected its arguments (version mismatch?)"
    if code is None:
        return "ghostbrain-capture check did not complete"
    return f"ghostbrain-capture check failed (exit {code})"


def _not_found_probe() -> HelperProbe:
    major, minor = macos_version()
    return HelperProbe(
        found=False, path=None, ok=False, code=None,
        reason=(f"{HELPER_NAME} not found; set {ENV_HELPER_BIN} or run "
                "scripts/build-native-macos.sh --install"),
        macos_version=f"{major}.{minor}", macos_supported=macos_supported(),
    )


_probe_lock = threading.Lock()
_probe_cache: tuple[float, HelperProbe] | None = None


def _run_check(helper: Path, *, audio_only: bool = False) -> HelperProbe:
    major, minor = macos_version()
    argv = [str(helper), "check", "--json"]
    if audio_only:
        argv.append("--audio-only")
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return HelperProbe(
            found=True, path=str(helper), ok=False, code=None,
            reason=f"{HELPER_NAME} check could not run: {e}",
            macos_version=f"{major}.{minor}", macos_supported=macos_supported(),
        )
    payload: dict[str, Any] = {}
    try:
        parsed = json.loads(proc.stdout.strip() or "{}")
        if isinstance(parsed, dict):
            payload = parsed
    except json.JSONDecodeError:
        payload = {}
    code = proc.returncode
    reason = _reason_for_code(code)
    issues = payload.get("issues")
    if code != EXIT_OK and isinstance(issues, list) and issues:
        reason = "; ".join(str(i) for i in issues)
    return HelperProbe(
        found=True, path=str(helper), ok=(code == EXIT_OK), code=code, reason=reason,
        macos_version=str(payload.get("macos") or f"{major}.{minor}"),
        macos_supported=(code != EXIT_MACOS_TOO_OLD and macos_supported()),
        screen_recording=str(payload.get("screen_recording") or "unknown"),
        microphone=str(payload.get("microphone") or "unknown"),
    )


def probe(*, force: bool = False) -> HelperProbe:
    """Run ``ghostbrain-capture check --json`` (cached for PROBE_TTL_S)."""
    global _probe_cache
    with _probe_lock:
        now = time.monotonic()
        if not force and _probe_cache is not None and now - _probe_cache[0] < PROBE_TTL_S:
            return _probe_cache[1]
        helper = find_helper()
        result = _run_check(helper) if helper else _not_found_probe()
        _probe_cache = (now, result)
        return result


def reset_probe_cache() -> None:
    global _probe_cache
    with _probe_lock:
        _probe_cache = None


def request_permissions() -> HelperProbe:
    """Trigger the macOS TCC prompts (the app only appears in the Screen
    Recording list after it has *attempted* access once), then re-probe."""
    helper = find_helper()
    if helper is None:
        return _not_found_probe()
    try:
        subprocess.run(
            [str(helper), "request-permissions"],
            capture_output=True, text=True,
            timeout=REQUEST_PERMISSIONS_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("request-permissions failed: %s", e)
    return probe(force=True)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def frames_dir_for(wav_path: Path) -> Path:
    """Slide frames live next to the WAV: ``meeting-x.wav`` → ``meeting-x.frames/``.
    Pure function of the WAV path, so no new state-file fields are needed."""
    return wav_path.with_suffix(".frames")


def control_file_for(wav_path: Path) -> Path:
    """Runtime control channel: ``meeting-x.wav`` → ``meeting-x.control.json``."""
    return wav_path.with_suffix(".control.json")


def write_control(wav_path: Path, choice: str, window_id: int | None = None) -> Path:
    """Answer the no-window prompt (or re-target mid-recording). ``choice`` is
    ``display`` / ``audio`` / ``window`` (the latter needs ``window_id``)."""
    if choice not in ("display", "audio", "window"):
        raise ValueError(f"unknown capture target choice {choice!r}")
    payload: dict[str, Any] = {"target": choice}
    if choice == "window":
        if not window_id or int(window_id) <= 0:
            raise ValueError("window choice requires a positive window_id")
        payload["window_id"] = int(window_id)
    path = control_file_for(wav_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, path)
    return path


def list_windows(wav_path: Path) -> list[dict[str, Any]]:
    """Pickable windows the helper published in ``<frames>/windows.json``
    (camelCase keys for the API). ``[]`` when unavailable."""
    catalog = frames_dir_for(wav_path) / "windows.json"
    try:
        data = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("windows") if isinstance(data, dict) else None
    out: list[dict[str, Any]] = []
    for w in raw or []:
        if not isinstance(w, dict):
            continue
        try:
            wid = int(w.get("window_id") or 0)
        except (TypeError, ValueError):
            continue
        if wid <= 0:
            continue
        out.append({
            "windowId": wid,
            "app": str(w.get("app") or ""),
            "appName": str(w.get("app_name") or w.get("app") or ""),
            "title": str(w.get("title") or ""),
            "width": int(w.get("width") or 0),
            "height": int(w.get("height") or 0),
            "candidate": bool(w.get("candidate")),
        })
    return out


def cleanup_control(wav_path: Path) -> None:
    try:
        control_file_for(wav_path).unlink()
    except OSError:
        pass


def _parse_kv_line(line: str) -> tuple[str, dict[str, str]]:
    """``KEY a=b c="quoted v"`` → ``("KEY", {"a": "b", "c": "quoted v"})``."""
    parts = line.strip().split(" ", 1)
    key = parts[0]
    fields: dict[str, str] = {}
    if len(parts) == 1:
        return key, fields
    rest = parts[1]
    i = 0
    n = len(rest)
    while i < n:
        while i < n and rest[i] == " ":
            i += 1
        eq = rest.find("=", i)
        if eq < 0:
            break
        name = rest[i:eq]
        i = eq + 1
        if i < n and rest[i] == '"':
            j = i + 1
            buf: list[str] = []
            while j < n:
                ch = rest[j]
                if ch == "\\" and j + 1 < n:
                    buf.append(rest[j + 1])
                    j += 2
                    continue
                if ch == '"':
                    break
                buf.append(ch)
                j += 1
            fields[name] = "".join(buf)
            i = j + 1
        else:
            j = rest.find(" ", i)
            if j < 0:
                j = n
            fields[name] = rest[i:j]
            i = j
    return key, fields


def enable_display_capture(pid: int) -> bool:
    """Answer the no-window prompt with "capture the whole display"."""
    return _signal(pid, signal.SIGUSR1)


def decline_display_capture(pid: int) -> bool:
    """Answer the no-window prompt with "audio only"."""
    return _signal(pid, signal.SIGUSR2)


def _signal(pid: int, sig: int) -> bool:
    if not audio_capture.is_running(pid):
        return False
    try:
        os.kill(pid, sig)
    except ProcessLookupError:
        return False
    return True


class NativeBackend:
    name = "native"

    def __init__(
        self,
        *,
        capture_slides: bool = True,
        slide_fps: int = 1,
        slide_fallback: str = "ask",
        target: str = "auto",
        ready_timeout_s: float = READY_TIMEOUT_S,
    ) -> None:
        self.capture_slides = capture_slides
        self.slide_fps = max(1, int(slide_fps))
        self.slide_fallback = slide_fallback
        self.target = target
        self.ready_timeout_s = ready_timeout_s

    # -- preflight / routing -------------------------------------------------

    def preflight(self) -> tuple[bool, list[str]]:
        p = probe()
        if p.ok:
            return True, []
        return False, [p.reason]

    def begin_meeting_route(self, device: str, fallback: str) -> RouteHandle:
        # System audio comes straight from ScreenCaptureKit; nothing to switch.
        return RouteHandle(previous_output="", switched=False)

    def end_meeting_route(self, handle: RouteHandle) -> None:
        # Normally a no-op. The exception is an upgrade mid-recording: the
        # daemon may finalize an ffmpeg/BlackHole recording started by the
        # previous build, whose stashed output device still needs restoring.
        if not handle.switched or not handle.previous_output:
            return
        try:
            from ghostbrain.recorder import audio_switcher
            audio_switcher.switch_to(handle.previous_output)
        except Exception as e:  # noqa: BLE001
            log.warning("could not restore audio output to %s: %s",
                        handle.previous_output, e)

    # -- capture ---------------------------------------------------------------

    def _argv(self, helper: Path, wav_path: Path) -> list[str]:
        argv = [
            str(helper), "run",
            "--wav", str(wav_path),
            "--target", self.target,
            "--no-window-policy", self.slide_fallback,
        ]
        if self.capture_slides:
            argv += ["--frames-dir", str(frames_dir_for(wav_path)),
                     "--control-file", str(control_file_for(wav_path)),
                     "--fps", str(self.slide_fps)]
        return argv

    def start_capture(self, wav_path: Path, *, log_path: Path | None = None) -> CaptureHandle:
        helper = find_helper()
        if helper is None:
            raise CaptureUnavailableError(_not_found_probe().reason)
        wav_path.parent.mkdir(parents=True, exist_ok=True)
        cleanup_control(wav_path)  # never replay a stale choice
        argv = self._argv(helper, wav_path)
        log.info("starting %s: %s", HELPER_NAME, " ".join(argv[1:]))

        err_target = open(log_path, "ab") if log_path else subprocess.DEVNULL
        try:
            proc = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=err_target,
                close_fds=True,
                start_new_session=True,
                text=True,
                bufsize=1,
            )
        finally:
            if log_path:
                try:
                    err_target.close()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass

        awaiting = self._wait_ready(proc)
        return CaptureHandle(pid=proc.pid, wav_path=wav_path, awaiting_target_choice=awaiting)

    def _wait_ready(self, proc: subprocess.Popen) -> bool:
        """Consume stdout until ``READY``. Returns whether the helper is
        waiting for a screen-capture choice. Raises on early exit/timeout."""
        assert proc.stdout is not None
        lines: list[str] = []
        done = threading.Event()

        def reader() -> None:
            try:
                for raw in proc.stdout:  # type: ignore[union-attr]
                    line = raw.rstrip("\n")
                    if not line:
                        continue
                    lines.append(line)
                    if line.startswith("READY"):
                        done.set()
                        return
            except (OSError, ValueError):
                pass
            finally:
                done.set()

        t = threading.Thread(target=reader, name="capture-ready", daemon=True)
        t.start()
        done.wait(self.ready_timeout_s)

        ready = any(l.startswith("READY") for l in lines)
        awaiting = False
        for line in lines:
            key, fields = _parse_kv_line(line)
            if key == "TARGET" and fields.get("kind") == "none" \
                    and fields.get("awaiting_choice") == "true":
                awaiting = True
            if key == "TARGET" and fields.get("kind") in ("window", "display"):
                awaiting = False

        if ready:
            # Detach: we must not hold the pipe open for the life of the
            # recording (the helper outlives this process on daemon restarts).
            try:
                proc.stdout.close()
            except OSError:
                pass
            return awaiting

        rc = proc.poll()
        if rc is None:
            # Still running but never said READY — give up on it.
            try:
                proc.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise RuntimeError(
                f"{HELPER_NAME} did not report READY within {self.ready_timeout_s:.0f}s"
            )
        try:
            proc.stdout.close()
        except OSError:
            pass
        if rc in _PRECONDITION_CODES:
            raise CaptureUnavailableError(_reason_for_code(rc))
        detail = "; ".join(lines[-3:]) if lines else "no output"
        raise RuntimeError(f"{HELPER_NAME} exited with code {rc} before READY ({detail})")

    def stop_capture(self, pid: int) -> bool:
        return audio_capture.stop_capture(pid, grace_s=STOP_GRACE_S)

    def capture_alive(self, pid: int) -> bool:
        return audio_capture.is_running(pid)
