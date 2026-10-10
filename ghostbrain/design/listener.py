"""Feeds a recording's live transcript into its design session.

Registered with :mod:`ghostbrain.recorder.live` at import: when live
transcription begins, a daemon thread follows ``live.follow(wav)`` and hands
every segment to the session (spoken commands are only detected while the
``design.listen`` setting is on; manual starts work either way). When the
recording finishes, the session ends. Nothing here may raise into the
recording.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from ghostbrain.design import session as design_session
from ghostbrain.recorder import live

log = logging.getLogger("ghostbrain.design.listener")

POLL_S = 2.0

_lock = threading.Lock()
_threads: dict[str, threading.Thread] = {}


def _recording_meta(wav: Path) -> tuple[str | None, str | None]:
    """(title, context) of the recording that writes ``wav``."""
    try:
        from ghostbrain.recorder import state as daemon_state

        active = daemon_state.load().active
        if active is not None and active.wav_path == str(wav):
            return active.title or None, active.context or None
    except Exception as e:  # noqa: BLE001
        log.debug("no daemon recording info: %s", e)
    try:
        from ghostbrain.api.repo import recorder as repo

        state = repo._read_state() or {}
        if state.get("wavPath") == str(wav):
            return state.get("title"), state.get("context")
    except Exception as e:  # noqa: BLE001
        log.debug("no manual recording info: %s", e)
    return None, None


def _pick_project(title: str | None, context: str | None) -> dict | None:
    """The project whose name appears in the meeting title (or vice versa),
    preferring the recording's own context."""
    if not title or not title.strip():
        return None
    from ghostbrain.api.repo import projects

    t = title.strip().lower()
    matches = []
    for p in projects.list_projects():
        name = str(p.get("name") or "").strip().lower()
        if name and (name in t or t in name):
            matches.append(p)
    matches.sort(key=lambda p: (p.get("context") != context, -len(str(p.get("name") or ""))))
    return matches[0] if matches else None


def _listen_enabled() -> bool:
    try:
        from ghostbrain.design import settings

        return bool(settings.load()["listen"])
    except Exception:  # noqa: BLE001
        return True


def _recording_in_progress(wav: Path) -> bool:
    try:
        from ghostbrain.api.repo.recorder import status

        st = status()
    except Exception:  # noqa: BLE001
        return False
    return st.get("phase") == "recording" and st.get("wavPath") == str(wav)


def session_for(wav: Path, *, threaded: bool = True) -> design_session.DesignSession:
    """The recording's session, creating it with the auto-picked project and
    design system."""
    existing = design_session.get(wav)
    if existing is not None:
        return existing
    title, context = _recording_meta(wav)
    project = None
    try:
        project = _pick_project(title, context)
    except Exception as e:  # noqa: BLE001
        log.warning("could not match a project for %r: %s", title, e)
    return design_session.ensure(
        wav, title=title, context=context,
        project_id=project["id"] if project else None,
        pack_id=(project or {}).get("design_system") or None,
        listening=_listen_enabled(), threaded=threaded,
    )


def _follow(wav: Path, threaded: bool) -> None:
    key = str(wav)
    try:
        s = session_for(wav, threaded=threaded)
        live_seen = False
        for event in live.follow(wav):
            if event is None:
                continue
            kind = event.get("type")
            if kind == "segment":
                s.on_segment(event)
            elif kind == "status":
                if event.get("state") in ("finalizing", "ended"):
                    break
                if event.get("state") != "off":
                    live_seen = True
            elif kind == "end":
                break
        if not live_seen:
            # No live transcription for this recording (switched off, or the
            # session belongs to another process): manual starts still work,
            # so keep the session until the recording stops.
            s.listening = False
            while _recording_in_progress(wav):
                time.sleep(POLL_S)
        s.end()
    except Exception:
        log.exception("design listener for %s failed", wav.name)
    finally:
        with _lock:
            if _threads.get(key) is threading.current_thread():
                del _threads[key]


def start_for_recording(wav: Path, *, threaded_session: bool = True) -> threading.Thread:
    """Create ``wav``'s session and follow its live transcript on a daemon
    thread (idempotent)."""
    wav = Path(wav)
    session_for(wav, threaded=threaded_session)
    with _lock:
        thread = _threads.get(str(wav))
        if thread is not None and thread.is_alive():
            return thread
        thread = threading.Thread(target=_follow, args=(wav, threaded_session), daemon=True,
                                  name="design-listener")
        _threads[str(wav)] = thread
        thread.start()
        return thread


def on_live_begin(wav: Path) -> None:
    """``live.begin`` hook: does its work off the recording-start path.
    Never raises."""
    def start() -> None:
        try:
            start_for_recording(wav)
        except Exception:
            log.exception("could not start the design listener for %s", Path(wav).name)

    try:
        threading.Thread(target=start, daemon=True, name="design-listener-start").start()
    except Exception:
        log.exception("could not start the design listener for %s", Path(wav).name)


live.on_begin(on_live_begin)
