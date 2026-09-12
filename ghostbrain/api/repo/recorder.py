"""Manual-recording control for the desktop app.

The sidecar owns the capture subprocess (native ``ghostbrain-capture``
helper or legacy ffmpeg) for manual sessions:

- POST /v1/recorder/start spawns capture, persists ``manual.state`` so the
  daemon's orphan-recovery flow can rescue it if the desktop closes
  mid-recording.
- POST /v1/recorder/stop SIGINTs capture and kicks off whisper transcription
  in a background thread, returning immediately. The UI polls /status.
- GET /v1/recorder/status reports the current phase based on whether the
  daemon owns a recording, whether capture is still alive for the manual
  state, or whether transcription is in flight / complete.
- POST /v1/recorder/capture/target answers the native helper's "no meeting
  window found" prompt (whole display / audio only / a specific window) by
  writing the helper's control file.

Background transcription writes the transcript markdown via
``ghostbrain.recorder.manual.recover_one``; once it returns, the state file
is updated with ``phase: done`` + the vault-relative transcript path so the
UI can transition to the post-meeting view.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.paths import vault_path
from ghostbrain.recorder import state as daemon_state
from ghostbrain.recorder.manual import load_config as load_manual_config, recover_one

log = logging.getLogger("ghostbrain.api.recorder")

from ghostbrain.recorder.config import DEFAULT_RECORDINGS_DIR

RECORDINGS_DIR = DEFAULT_RECORDINGS_DIR
STATE_FILE = RECORDINGS_DIR.parent / "manual.state"

_lock = threading.Lock()


class RecorderBusy(Exception):
    pass


class RecorderNotActive(Exception):
    pass


class RecorderUnsupportedError(Exception):
    """Raised when the current platform has no audio backend at runtime."""
    pass


def _ensure_supported() -> None:
    from ghostbrain.recorder.audio import UnsupportedBackend, get_backend

    backend = get_backend()
    if isinstance(backend, UnsupportedBackend):
        raise RecorderUnsupportedError(backend.platform_message)


def _read_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("manual.state unreadable, treating as idle: %s", e)
        return None


def _write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _clear_state() -> None:
    if STATE_FILE.exists():
        try:
            STATE_FILE.unlink()
        except OSError:
            pass


def _daemon_active() -> dict | None:
    """Daemon-owned (calendar-driven) recording info, if one is live."""
    from ghostbrain.recorder.audio import get_backend

    ds = daemon_state.load()
    if ds.active is None:
        return None
    if not get_backend().capture_alive(ds.active.pid):
        return None
    return ds.active.to_dict()


def _vault_relative(path: Path) -> str | None:
    try:
        return str(path.resolve().relative_to(vault_path().resolve()))
    except ValueError:
        return None


def _source_exclusions() -> list[str]:
    """Human-readable reasons a configured calendar isn't driving
    auto-record (spec §4). Must never fail status() — any error loading
    or parsing the vault's routing/recorder config degrades to []."""
    from ghostbrain.recorder.daemon import DaemonConfig
    from ghostbrain.recorder.sources import select_sources

    try:
        config = DaemonConfig.load()
        _, exclusions = select_sources(config.routing, config.recorder_cfg)
    except Exception as e:  # noqa: BLE001
        log.warning("could not compute recorder source exclusions: %s", e)
        return []
    return exclusions


def status() -> dict:
    """Snapshot the current recording phase across daemon + manual states."""
    _ensure_supported()
    exclusions = _source_exclusions()
    daemon = _daemon_active()
    if daemon is not None:
        return {
            "phase": "recording",
            "owner": "daemon",
            "title": daemon.get("title"),
            "startedAt": daemon.get("started_at"),
            "wavPath": daemon.get("wav_path"),
            "transcriptPath": None,
            "error": None,
            "sourceExclusions": exclusions,
            "captureBackend": daemon.get("capture_backend") or None,
            "awaitingTargetChoice": bool(daemon.get("awaiting_target_choice")),
            "captureWindows": _capture_windows(
                daemon.get("wav_path"), bool(daemon.get("awaiting_target_choice")),
            ),
        }
    state = _read_state()
    if state is None:
        return {
            "phase": "idle",
            "owner": None,
            "title": None,
            "startedAt": None,
            "wavPath": None,
            "transcriptPath": None,
            "error": None,
            "sourceExclusions": exclusions,
            "captureBackend": None,
            "awaitingTargetChoice": False,
            "captureWindows": [],
        }
    phase = state.get("phase", "idle")
    # If the state claims "recording" but capture died, the user (or a crash)
    # stopped it without going through our /stop endpoint. Promote to
    # "transcribing" so the next /stop call (or daemon recovery) handles it.
    if phase == "recording":
        from ghostbrain.recorder.audio import get_backend

        pid = state.get("pid")
        if not (isinstance(pid, int) and get_backend().capture_alive(pid)):
            phase = "transcribing"
            state["phase"] = phase
            _write_state(state)
    return {
        "phase": phase,
        "owner": "manual",
        "title": state.get("title"),
        "startedAt": state.get("startedAt"),
        "wavPath": state.get("wavPath"),
        "transcriptPath": state.get("transcriptPath"),
        "error": state.get("error"),
        "sourceExclusions": exclusions,
        "captureBackend": state.get("captureBackend"),
        "awaitingTargetChoice": bool(
            phase == "recording" and state.get("awaitingTargetChoice")
        ),
        "captureWindows": _capture_windows(
            state.get("wavPath"), bool(phase == "recording" and state.get("awaitingTargetChoice")),
        ),
    }


def _capture_windows(wav_path: str | None, awaiting: bool) -> list[dict]:
    """Pickable windows from the helper's catalog, only while a choice is pending."""
    if not awaiting or not wav_path or sys.platform != "darwin":
        return []
    try:
        from ghostbrain.recorder.audio import darwin_native
        return darwin_native.list_windows(Path(wav_path))
    except Exception as e:  # noqa: BLE001
        log.warning("could not list capture windows: %s", e)
        return []


def _current_calendar_event() -> dict | None:
    """If a calendar event is happening right now, return its frontmatter +
    vault-relative path so a manual recording can inherit the context.

    Picks the event whose [start, end] window contains now. If multiple
    overlap, returns the one with the longest remaining time (best signal
    of "the meeting I'm in").
    """
    import frontmatter

    from ghostbrain.paths import vault_path

    now = datetime.now(timezone.utc)
    best: tuple[float, dict, Path] | None = None
    for path in vault_path().glob("20-contexts/*/calendar/*.md"):
        try:
            post = frontmatter.load(path)
        except Exception:  # noqa: BLE001
            continue
        fm = post.metadata
        start_raw = fm.get("start")
        end_raw = fm.get("end")
        if not isinstance(start_raw, str) or not isinstance(end_raw, str):
            continue
        try:
            start_dt = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        # All-day entries (leave, room blocks) are written as date-only
        # strings, which parse to *naive* datetimes. They aren't meetings to
        # record against, and comparing naive with aware ``now`` raises
        # TypeError — which used to escape this loop and 500 the whole
        # /start request. Skip anything without a timezone.
        if start_dt.tzinfo is None or end_dt.tzinfo is None:
            continue
        if not (start_dt <= now <= end_dt):
            continue
        remaining = (end_dt - now).total_seconds()
        if best is None or remaining > best[0]:
            best = (remaining, dict(fm), path)
    if best is None:
        return None
    _, fm, path = best
    try:
        rel_path = str(path.resolve().relative_to(vault_path().resolve()))
    except ValueError:
        rel_path = None
    return {"frontmatter": fm, "rel_path": rel_path}


def start(title: str | None, context: str | None) -> dict:
    _ensure_supported()
    with _lock:
        if _daemon_active() is not None:
            raise RecorderBusy("calendar-driven recording is in progress")
        existing = _read_state()
        if existing and existing.get("phase") in ("recording", "transcribing"):
            raise RecorderBusy(f"a manual recording is already {existing['phase']}")

        manual_cfg = load_manual_config()
        # Priority: explicit context arg > active calendar event's context >
        # config default. The middle case is what most user "I'm in a meeting"
        # presses should hit.
        active_event = _current_calendar_event() if context is None else None
        active_context = (
            str(active_event["frontmatter"].get("context"))
            if active_event and isinstance(active_event["frontmatter"].get("context"), str)
            else None
        )
        chosen_context = context or active_context or manual_cfg.context
        # If we found an active event, also pick up its title (so the user
        # doesn't have to type it) and remember the event note for the
        # parent wikilink at transcribe time.
        chosen_title = title or (
            str(active_event["frontmatter"].get("title"))
            if active_event and isinstance(active_event["frontmatter"].get("title"), str)
            else None
        )
        parent_path = active_event["rel_path"] if active_event else None

        from ghostbrain.recorder.audio import get_backend

        backend = get_backend()
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        wav_path = RECORDINGS_DIR / f"meeting-{timestamp}-manual.wav"
        log_path = RECORDINGS_DIR / "capture.log"
        handle = backend.start_capture(wav_path, log_path=log_path)

        state = {
            "phase": "recording",
            "pid": handle.pid,
            "wavPath": str(handle.wav_path),
            "captureBackend": getattr(backend, "name", None),
            "awaitingTargetChoice": bool(getattr(handle, "awaiting_target_choice", False)),
            "title": chosen_title,  # may be null; LLM derives if stop-time title still missing
            "context": chosen_context,
            "parentPath": parent_path,  # vault-relative path of the linked calendar event
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "transcriptPath": None,
            "error": None,
        }
        _write_state(state)
        log.info(
            "manual recording started pid=%d wav=%s ctx=%s parent=%s",
            handle.pid, handle.wav_path.name, chosen_context, parent_path or "-",
        )
        return state


def stop() -> dict:
    _ensure_supported()
    from ghostbrain.recorder.audio import get_backend

    backend = get_backend()
    with _lock:
        # Daemon-owned (calendar-driven) recording: stop capture and let
        # the recorder daemon's next tick run _finalize (transcribe, link
        # to vault, restore audio output). status() drops the daemon
        # record as soon as the pid is gone, so the UI flips to idle.
        ds = daemon_state.load()
        if ds.active is not None and backend.capture_alive(ds.active.pid):
            backend.stop_capture(ds.active.pid)
            return status()

        state = _read_state()
        if state is None or state.get("phase") not in ("recording", "transcribing"):
            raise RecorderNotActive("no recording to stop")

        if state.get("phase") == "recording":
            pid = state.get("pid")
            if isinstance(pid, int):
                backend.stop_capture(pid)
            state["phase"] = "transcribing"
            _write_state(state)

        # Kick off transcription in a daemon thread so the endpoint returns
        # immediately. The UI polls /status until phase=done.
        thread = threading.Thread(
            target=_transcribe_in_background,
            args=(dict(state),),
            daemon=True,
            name="recorder-transcribe",
        )
        thread.start()
        return state


def _transcribe_in_background(snapshot: dict) -> None:
    wav = Path(snapshot["wavPath"])
    title = snapshot.get("title")
    context = snapshot.get("context") or load_manual_config().context
    started_iso = snapshot.get("startedAt") or ""
    try:
        started = datetime.fromisoformat(started_iso.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        started = None

    cfg = dataclasses.replace(load_manual_config(), context=context)
    parent_path = snapshot.get("parentPath")
    try:
        transcript_path = recover_one(
            wav,
            cfg,
            title_override=title,
            started_override=started,
            parent_path_override=parent_path,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("transcription failed for %s", wav.name)
        with _lock:
            current = _read_state() or {}
            current.update({
                "phase": "done",
                "error": f"transcription failed: {e}",
            })
            _write_state(current)
        return

    rel = _vault_relative(transcript_path) if transcript_path is not None else None
    with _lock:
        current = _read_state() or {}
        current.update({
            "phase": "done",
            "transcriptPath": rel,
            "error": None,
        })
        _write_state(current)
    log.info("manual recording transcribed: %s", rel or "(failed)")


def request_capture_permissions() -> dict:
    """Trigger the native helper's TCC prompts, then return the fresh probe."""
    _ensure_supported()
    if sys.platform != "darwin":
        raise RecorderUnsupportedError("native capture permissions only apply on macOS")
    from ghostbrain.recorder.audio import darwin_native

    return darwin_native.request_permissions().to_dict()


def set_capture_target(choice: str, window_id: int | None = None) -> dict:
    """Answer the native helper's "no meeting window" prompt for whichever
    recording (daemon- or manual-owned) is live, then return status().

    ``choice`` is ``display`` / ``audio`` / ``window`` (+ ``window_id`` from
    ``status().captureWindows``). Delivered via the helper's control file."""
    _ensure_supported()
    if sys.platform != "darwin":
        raise RecorderUnsupportedError("capture target choice only applies on macOS")
    from ghostbrain.recorder.audio import darwin_native, get_backend

    backend = get_backend()

    with _lock:
        ds = daemon_state.load()
        if ds.active is not None and backend.capture_alive(ds.active.pid):
            darwin_native.write_control(Path(ds.active.wav_path), choice, window_id)
            ds.active.awaiting_target_choice = False
            daemon_state.save(ds)
            return status()

        state = _read_state()
        if state is None or state.get("phase") != "recording":
            raise RecorderNotActive("no recording to retarget")
        pid = state.get("pid")
        if not (isinstance(pid, int) and backend.capture_alive(pid)):
            raise RecorderNotActive("capture process is not running")
        wav = state.get("wavPath")
        if not isinstance(wav, str) or not wav:
            raise RecorderNotActive("recording has no wav path")
        darwin_native.write_control(Path(wav), choice, window_id)
        state["awaitingTargetChoice"] = False
        _write_state(state)
        return status()


def clear() -> dict:
    """Acknowledge a 'done' recording. UI calls this to reset to idle."""
    _ensure_supported()
    with _lock:
        state = _read_state()
        if state is None:
            return status()
        if state.get("phase") in ("recording", "transcribing"):
            # Refuse — caller should stop first.
            raise RecorderBusy(f"refusing to clear while {state['phase']}")
        _clear_state()
        return status()
