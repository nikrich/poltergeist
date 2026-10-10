"""Live transcription while a meeting is being recorded.

When a recording starts, :func:`begin` starts a warm whisper-server and a
thread that follows the growing WAV, transcribing pause-aligned chunks
(each with its own language detection) and appending the segments to
``<recording>.live.jsonl``. Subscribers (the ``/v1/recorder/live`` SSE route)
get every segment as it lands; :func:`follow` replays the file first so a
window opened mid-meeting catches up.

Live text is a preview. When the recording stops, the final pass takes the
same warm server via :func:`final_pass_server` and re-transcribes the whole
file in longer chunks for the saved note, then closes the session.

Nothing here may affect the recording itself: every failure degrades to
``state: unavailable`` with a reason, and the final pass falls back to
``whisper-cli``.
"""
from __future__ import annotations

import contextlib
import json
import logging
import queue
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ghostbrain.recorder import chunker
from ghostbrain.recorder.config import AUTO_LANGUAGES
from ghostbrain.recorder.whisper_server import WhisperServer, WhisperServerError

log = logging.getLogger("ghostbrain.recorder.live")

# Used instead of chunker.LIVE once transcription falls behind real time:
# fewer, longer chunks cost less per second of audio, so the backlog drains.
CATCH_UP = chunker.Profile(min_s=8.0, max_s=24.0)

ServerFactory = Callable[[], Any]  # returns a started-on-demand WhisperServer

_registry_lock = threading.Lock()
_sessions: dict[str, LiveSession] = {}
# Called with the WAV path whenever live transcription begins for a new
# recording (the design listener registers here). Failures are logged only.
_on_begin: list[Callable[[Path], None]] = []


def on_begin(callback: Callable[[Path], None]) -> None:
    """Run ``callback(wav)`` each time live transcription begins."""
    if callback not in _on_begin:
        _on_begin.append(callback)


def live_path(wav: Path) -> Path:
    return wav.with_suffix(".live.jsonl")


def read_chunks(wav: Path) -> list[dict]:
    """The per-chunk language records live transcription wrote, in order."""
    path = live_path(wav)
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("type") == "chunk":
            out.append(record)
    return out


def _resume_point(wav: Path) -> tuple[int, int]:
    """(first sample not yet transcribed, last segment seq) from live.jsonl."""
    path = live_path(wav)
    if not path.exists():
        return 0, 0
    pos = seq = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if record.get("type") == "chunk":
            pos = max(pos, int(record.get("end", 0)))
        elif record.get("type") == "segment":
            seq = max(seq, int(record.get("seq", 0)))
    return pos, seq


def language_runs(chunks: list[dict]) -> list[tuple[int, int, str]]:
    """Merge consecutive chunks into (start, end, lang) runs of one language.
    Silent chunks (lang None) join the run before them — or the first run,
    when they lead. No language anywhere means no runs."""
    runs: list[list] = []
    lead: int | None = None  # start of silence before the first language
    for c in chunks:
        lang = c.get("lang")
        if lang is None:
            if runs:
                runs[-1][1] = c["end"]
            elif lead is None:
                lead = c["start"]
        elif runs and runs[-1][2] == lang:
            runs[-1][1] = c["end"]
        elif runs:
            runs.append([runs[-1][1], c["end"], lang])
        else:
            runs.append([c["start"] if lead is None else lead, c["end"], lang])
    return [(int(start), int(end), str(lang)) for start, end, lang in runs]


def default_server_factory() -> WhisperServer:
    from ghostbrain.recorder.transcribe import _resolve_model

    return WhisperServer(_resolve_model(None))


class LiveSession:
    def __init__(self, wav: Path, server_factory: ServerFactory, language: str, poll_s: float):
        self.wav = wav
        self._factory = server_factory
        self._language = language
        self._poll_s = poll_s
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self._seq = 0
        self._state = "starting"
        self._reason: str | None = None
        self._lag_s = 0.0
        self._stop = threading.Event()
        self._server: Any = None
        # A recording that outlived the sidecar that started live transcription
        # (app restart mid-meeting) resumes where that session left off.
        self._resume_pos, self._seq = _resume_point(wav)
        self._thread = threading.Thread(target=self._run, daemon=True, name="recorder-live")

    # -- public -----------------------------------------------------------

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def subscribe(self) -> tuple[queue.Queue, int]:
        """A queue of future events plus the last seq already on disk."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.append(q)
            return q, self._seq

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def stop_live(self) -> None:
        """Stop following the WAV (recording ended). Keeps the server warm."""
        self._stop.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=180)
        with self._lock:
            if self._state in ("starting", "live"):
                self._state = "finalizing"
                self._publish_locked(self._status_locked())

    def take_server(self) -> Any:
        server, self._server = self._server, None
        return server

    def close(self) -> None:
        """Final pass done: tell subscribers, drop the preview file."""
        with self._lock:
            self._state = "ended"
            self._publish_locked(self._status_locked())
            self._publish_locked({"type": "end"})
        try:
            live_path(self.wav).unlink(missing_ok=True)
        except OSError:
            pass

    # -- internals --------------------------------------------------------

    def _status_locked(self) -> dict:
        return {
            "type": "status",
            "state": self._state,
            "reason": self._reason,
            "lag_s": round(self._lag_s, 1),
        }

    def _publish_locked(self, event: dict) -> None:
        for q in self._subs:
            q.put(event)

    def _set(self, state: str, reason: str | None = None) -> None:
        with self._lock:
            self._state = state
            self._reason = reason
            self._publish_locked(self._status_locked())

    def _fail(self, reason: str) -> None:
        log.warning("live transcription unavailable for %s: %s", self.wav.name, reason)
        if self._server is not None:
            self._server.stop()
            self._server = None
        self._set("unavailable", reason)

    def _emit(self, chunk: chunker.Chunk, segments: list) -> None:
        segments = drop_hallucinations(chunk, segments)
        path = live_path(self.wav)
        end = chunk.start_sample + len(chunk.pcm) // chunker.BYTES_PER_SAMPLE
        # What language this stretch of audio is in (None = no speech) — the
        # final pass uses it to keep its longer chunks inside one language.
        record = {
            "type": "chunk", "start": chunk.start_sample, "end": end,
            "lang": segments[0].lang if segments else None,
        }
        with self._lock, path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
            for seg in segments:
                self._seq += 1
                event = {"type": "segment", "seq": self._seq, **seg.to_dict()}
                f.write(json.dumps(event) + "\n")
                self._publish_locked(event)

    def _run(self) -> None:
        try:
            self._server = self._factory()
            self._server.start()
        except Exception as e:  # noqa: BLE001 — never let live take the recording down
            self._fail(str(e))
            return
        self._set("live")

        pos = self._resume_pos
        restarted = False
        while not self._stop.is_set():
            profile = CATCH_UP if self._lag_s > chunker.LIVE.max_s else chunker.LIVE
            chunk = chunker.next_chunk(self.wav, pos, profile)
            if chunk is None:
                self._stop.wait(self._poll_s)
                continue
            try:
                segments = self._server.transcribe(
                    chunk.pcm, language=self._language, offset_s=chunk.start_s,
                    allowed=AUTO_LANGUAGES if self._language == "auto" else None,
                )
            except Exception as e:  # noqa: BLE001
                if restarted:
                    self._fail(f"whisper-server failed twice: {e}")
                    return
                restarted = True
                log.warning("whisper-server failed (%s); restarting once", e)
                try:
                    self._server.stop()
                    self._server.start()
                except Exception as e2:  # noqa: BLE001
                    self._fail(str(e2))
                    return
                continue  # retry the same chunk
            self._emit(chunk, segments)
            pos += len(chunk.pcm) // chunker.BYTES_PER_SAMPLE
            self._update_lag(pos)

    def _update_lag(self, pos: int) -> None:
        try:
            total = (self.wav.stat().st_size - chunker.WAV_HEADER_BYTES) // chunker.BYTES_PER_SAMPLE
        except OSError:
            return
        with self._lock:
            self._lag_s = max(0, total - pos) / chunker.SAMPLE_RATE
            self._publish_locked(self._status_locked())


def drop_hallucinations(chunk: chunker.Chunk, segments: list) -> list:
    """``segments`` without whisper's "Thank you." on near-silent audio."""
    if not any(chunker._HALLUCINATIONS.match(s.text.strip()) for s in segments):
        return segments
    kept = []
    for seg in segments:
        a = max(0, int((seg.t0 - chunk.start_s) * chunker.SAMPLE_RATE)) * chunker.BYTES_PER_SAMPLE
        b = max(a, int((seg.t1 - chunk.start_s) * chunker.SAMPLE_RATE)) * chunker.BYTES_PER_SAMPLE
        if not chunker.is_hallucination(seg.text, chunk.pcm[a:b] or chunk.pcm):
            kept.append(seg)
    return kept


def begin(
    wav: Path,
    *,
    server_factory: ServerFactory | None = None,
    language: str = "auto",
    poll_s: float = 1.0,
) -> LiveSession | None:
    """Start live transcription for a recording. Never raises."""
    key = str(wav)
    try:
        with _registry_lock:
            if key in _sessions:
                return _sessions[key]
            session = LiveSession(wav, server_factory or default_server_factory, language, poll_s)
            _sessions[key] = session
        session._thread.start()
    except Exception:
        log.exception("could not start live transcription for %s", wav.name)
        return None
    for callback in _on_begin:
        try:
            callback(wav)
        except Exception:  # listeners never affect the recording
            log.exception("live begin hook failed for %s", wav.name)
    return session


def begin_from_config(
    wav: Path, *, server_factory: Callable[[Path], Any] | None = None,
) -> LiveSession | None:
    """:func:`begin` with the vault's recorder settings, or None when live
    transcription is switched off. ``server_factory`` takes the model path."""
    from ghostbrain.recorder import config as rcfg
    from ghostbrain.recorder.transcribe import TranscribeError, _resolve_model, is_multilingual

    try:
        rec = rcfg.load_recorder_block()
    except Exception:  # noqa: BLE001
        rec = {}
    if not rcfg.live_transcription_from(rec):
        return None
    language = rcfg.transcription_language_from(rec)
    make = server_factory or WhisperServer
    try:
        model = _resolve_model(None)
    except TranscribeError as e:
        # Surface "no model" in the live panel rather than silently skipping.
        reason = str(e)

        def missing() -> Any:
            raise WhisperServerError(reason)

        return begin(wav, server_factory=missing, language=language)
    if not is_multilingual(model):
        language = "en"
    return begin(wav, server_factory=lambda: make(model), language=language)


def current() -> LiveSession | None:
    """The live session for the recording in progress (one at a time)."""
    with _registry_lock:
        return next(reversed(_sessions.values()), None)


def follow(
    wav: Path | None = None, *, keepalive_s: float = 15.0, enabled: bool = True,
) -> Iterator[dict | None]:
    """Replay a session's segments, then stream new events until ``end``.
    Yields None every ``keepalive_s`` of quiet so SSE can send a heartbeat.
    ``enabled=False`` (setting switched off) says so instead of streaming."""
    if not enabled:
        yield {"type": "status", "state": "off", "reason": None, "lag_s": 0.0}
        yield {"type": "end"}
        return
    with _registry_lock:
        session = _sessions.get(str(wav)) if wav is not None else next(
            reversed(_sessions.values()), None,
        )
    if session is None:
        yield {"type": "end"}
        return

    q, last_seq = session.subscribe()
    try:
        path = live_path(session.wav)
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "segment" and event.get("seq", 0) <= last_seq:
                    yield event
        status = session.status()
        yield status
        if status["state"] == "ended":
            yield {"type": "end"}
            return
        while True:
            try:
                event = q.get(timeout=keepalive_s)
            except queue.Empty:
                yield None
                continue
            yield event
            if event.get("type") == "end":
                return
    finally:
        session.unsubscribe(q)


@contextlib.contextmanager
def final_pass_server(
    wav: Path, *, server_factory: ServerFactory | None = None,
) -> Iterator[Any]:
    """The warm server for the final pass — the live session's if it has one,
    else a freshly started one, else None (caller falls back to whisper-cli).
    Stops the server and closes the live session on exit."""
    with _registry_lock:
        session = _sessions.get(str(wav))
    server = None
    if session is not None:
        session.stop_live()
        server = session.take_server()
    if server is None or not server.alive():
        try:
            server = (server_factory or default_server_factory)()
            server.start()
        except Exception as e:  # noqa: BLE001
            log.info("no whisper-server for the final pass (%s); using whisper-cli", e)
            server = None
    try:
        yield server
    finally:
        if server is not None:
            server.stop()
        if session is not None:
            session.close()
            with _registry_lock:
                _sessions.pop(str(wav), None)
        # Also when the session belonged to a sidecar that has since exited.
        try:
            live_path(wav).unlink(missing_ok=True)
        except OSError:
            pass


def stop_all() -> None:
    """Stop every live session and its server (sidecar shutdown, tests)."""
    with _registry_lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for s in sessions:
        s.stop_live()
        server = s.take_server()
        if server is not None:
            server.stop()
