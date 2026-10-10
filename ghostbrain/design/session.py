"""The live design session: one per recording, a small state machine per
canvas (``ui`` prototype, ``board`` event storm) and the run loop that keeps
them up to date while the meeting talks.

Transcript segments arrive through :meth:`DesignSession.on_segment` (fed by
:mod:`ghostbrain.design.listener`). An intake thread checks each one for a
spoken command and routes design talk into the focused canvas's buffer; a
1 s tick decides when a buffer is worth a run; a single worker thread runs
the agents, so at most one run is in flight per canvas and triggers that
arrive mid-run coalesce into the next one.

Every state change is published to subscribers (the ``/v1/design/live``
SSE route) and appended to ``session.jsonl`` in the prototype folder, from
which a restarted sidecar rebuilds the session. Nothing here may raise into
the recording: listener-facing entry points catch and log.

The UI canvas is either a ``scratch`` prototype (``src/`` in the folder,
bundled by the desktop) or a ``worktree`` of an existing frontend repo: the
folder then only holds the session files and the code lives in a sibling git
worktree, where the first run makes the app work offline (``bootstrap``) and
later runs may not touch its run config (reverted after every run). A repo
named in the meeting is only a suggestion: nothing is created, installed or
run in it until the user confirms it in the panel (``set_codebase``).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ghostbrain.design import (
    board_agent,
    codebases,
    commands,
    relevance,
    scaffold,
    ui_agent,
    worktree,
)
from ghostbrain.design.commands import Command
from ghostbrain.design.relevance import Buffer, Segment

log = logging.getLogger("ghostbrain.design.session")

CANVASES = ("ui", "board")
WINDOW_S = 45.0
# Relevance judges the speech since the last run, back this far.
JUDGE_S = 60.0
# Cap on what a canvas keeps between runs (segments).
HEARD_MAX = 400
# Whisper often splits one sentence over several segments ("let's start a
# design session" / "a front-end prototype"): command detection judges the
# speech since the last command, back to this many seconds, as one utterance.
UTTERANCE_S = 12.0
UNDO_TTL_S = 120.0
MAX_FAILURES = 3
MAX_FIX_RUNS = 2
END_TIMEOUT_S = 900.0
PROVIDER_REASON = "Live prototyping needs the Claude provider"
RESTART_REASON = "Resumed after restart"
CONFIRM_REASON = "Confirm the repo to start"
DEFAULT_BUDGET_USD = 2.0

_NAMES = {"ui": "frontend prototype", "board": "event-storming board", "both": "design session"}
_UNSET: Any = object()


class SessionError(Exception):
    """An action the session cannot take right now (routes answer 409)."""


class _Unavailable(Exception):
    """The canvas cannot run at all; the reason is shown in the panel."""


class _Discarded(Exception):
    """The codebase changed while the run was in flight; drop its result."""


def _provider_id() -> str | None:
    try:
        from ghostbrain.llm.providers import get_provider

        return getattr(get_provider(), "id", None)
    except Exception as e:  # noqa: BLE001
        log.warning("could not resolve the LLM provider: %s", e)
        return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:60].rstrip("-")


def _web() -> bool:
    try:
        from ghostbrain.design import settings

        return bool(settings.load()["web"])
    except Exception:  # noqa: BLE001
        return True


def _budget() -> float:
    try:
        from ghostbrain.design import settings

        return float(settings.load()["budget_usd"])
    except Exception:  # noqa: BLE001
        return DEFAULT_BUDGET_USD


def _default_pack() -> str:
    try:
        from ghostbrain.design import settings

        return str(settings.load()["default_pack"])
    except Exception:  # noqa: BLE001
        from ghostbrain.design import packs

        return packs.BUILTIN_PACK_ID


def _default_context() -> str:
    try:
        from ghostbrain.recorder.manual import load_config

        return load_config().context
    except Exception:  # noqa: BLE001
        return "personal"


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def _write_artefact(folder: Path, data: dict) -> None:
    from ghostbrain.design import artefacts

    artefacts.write(folder, data)


def _load_artefact(folder: Path) -> dict | None:
    from ghostbrain.design import artefacts

    return artefacts.load(folder)


def pointer_path(wav: Path) -> Path:
    """Where the sidecar remembers which prototype folder a recording uses."""
    from ghostbrain.recorder.state import state_dir

    key = hashlib.sha1(str(wav).encode("utf-8")).hexdigest()[:16]
    return state_dir() / "design" / f"{key}.json"


class _Canvas:
    def __init__(self, clock: Callable[[], float]) -> None:
        self.state = "off"
        self.rev = 0
        self.running = False
        self.reason: str | None = None
        self.last_error: str | None = None
        self.revs: list[dict] = []
        self.buffer = Buffer(clock=clock)
        self.nudges: list[str] = []
        self.failures = 0
        self.fix_runs = 0
        self.build_error: str | None = None
        self.consumed_seq = 0
        # Everything said to this canvas since its last run, relevant or not:
        # whisper cuts sentences into fragments, so a fragment alone is often
        # "irrelevant" while the utterance it belongs to is the requirement.
        self.heard: list[Segment] = []

    def snapshot(self) -> dict:
        return {
            "state": self.state,
            "rev": self.rev,
            "running": self.running,
            "buffered_s": round(self.buffer.speech_s, 1),
            "reason": self.reason,
            "last_error": self.last_error,
            "revs": [dict(r) for r in self.revs],
        }

    def persist(self) -> dict:
        return {
            "state": self.state, "rev": self.rev, "reason": self.reason,
            "last_error": self.last_error, "revs": self.revs,
            "consumed_seq": self.consumed_seq, "fix_runs": self.fix_runs,
        }


class DesignSession:
    def __init__(
        self,
        wav: Path,
        *,
        title: str | None,
        context: str,
        project_id: str | None = None,
        pack_id: str | None = None,
        listening: bool = True,
        clock: Callable[[], float] = time.monotonic,
        threaded: bool = True,
        today: date | None = None,
        session_id: str | None = None,
    ) -> None:
        self.wav = Path(wav)
        self.id = session_id or uuid.uuid4().hex[:12]
        self.recording_title = title
        self.context = context
        self.project_id = project_id
        self.pack_id = pack_id or _default_pack()
        self.listening = listening
        self.focus: str | None = None
        self.board: dict | None = None
        self.ui_session_id: str | None = None
        self.ended = False
        # Project brief per project id (built once, off the lock), and which
        # project the UI agent's CLI session already has it for.
        self._briefs: dict[str, str] = {}
        self._brief_sent_for: str | None = None

        self._clock = clock
        self._today = today or date.today()
        self._lock = threading.RLock()
        self._cv = threading.Condition(self._lock)
        self._subs: list[queue.Queue] = []
        self.canvases = {c: _Canvas(clock) for c in CANVASES}
        self._board_history: dict[int, dict] = {0: board_agent.empty_model()}
        self._window: list[Segment] = []
        self._last_seq = 0
        self._command_seq = 0
        self._undo: dict[str, tuple[float, dict]] = {}
        self._pending: list[str] = []
        self._busy = False
        self._ending = False
        self._stopped = False
        self._dir: Path | None = None
        # Worktree mode: the repo picked (``{"repo", "name"}``) and, once the UI
        # starts, its worktree. The protected-file snapshot taken after the
        # bootstrap run lives in protected.json, out of the agent's reach.
        self.ui_kind = "scratch"
        self.codebase: worktree.Worktree | None = None
        self._choice: dict | None = None
        # False while a repo picked by voice awaits the user's confirmation.
        self.codebase_confirmed = True
        self.install = "idle"
        self._bootstrapped = False
        self._protected: dict | None = None
        self._codebase_gen = 0
        self._planned = self._plan_dir()

        self._threaded = threaded
        self._intake: queue.Queue = queue.Queue()
        if threaded:
            threading.Thread(target=self._intake_loop, daemon=True, name="design-intake").start()
            threading.Thread(target=self._worker_loop, daemon=True, name="design-worker").start()

    # -- read side -------------------------------------------------------------

    @property
    def prototype_dir(self) -> str:
        return str(self._dir or self._planned)

    def snapshot(self) -> dict:
        from ghostbrain.paths import vault_path

        with self._lock:
            folder = self._dir or self._planned
            try:
                rel = folder.relative_to(vault_path()).as_posix()
            except ValueError:
                rel = str(folder)
            return {
                "id": self.id,
                "recording_title": self.recording_title,
                "context": self.context,
                "project_id": self.project_id,
                "pack_id": self.pack_id,
                "prototype_dir": str(folder),
                "prototype_rel": rel,
                "focus": self.focus,
                "listening": self.listening,
                "canvases": {c: cv.snapshot() for c, cv in self.canvases.items()},
                "board": json.loads(json.dumps(self.board)) if self.board is not None else None,
                "ui_kind": self.ui_kind,
                "codebase": self._codebase_info(),
                "install": self.install,
                "codebase_confirmed": self.codebase_confirmed,
                "artefact_rel": rel,
            }

    def _codebase_info(self) -> dict | None:
        if self.codebase is not None:
            return self.codebase.to_dict()
        if self._choice is not None:  # picked; the worktree is made when the UI starts
            return {"repo": self._choice["repo"], "name": self._choice["name"], "app_dir": "",
                    "worktree": "", "branch": "", "base": ""}
        return None

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _publish(self, event: dict) -> None:
        with self._lock:
            for q in self._subs:
                q.put(event)

    def _emit_snapshot(self) -> None:
        self._publish({"type": "snapshot", "session": self.snapshot()})

    # -- transcript intake -----------------------------------------------------

    def on_segment(self, seg: dict) -> None:
        """A live transcript segment. Never raises."""
        try:
            if self._threaded:
                self._intake.put(seg)
            else:
                self._process([seg])
        except Exception:
            log.exception("design session could not take a segment")

    def _intake_loop(self) -> None:
        while not self._stopped:
            batch: list[dict] = []
            try:
                batch.append(self._intake.get(timeout=1.0))
                while True:
                    batch.append(self._intake.get_nowait())
            except queue.Empty:
                pass
            try:
                if batch:
                    self._process(batch)
                self.tick()
            except Exception:
                log.exception("design intake failed")

    def _process(self, batch: list[dict]) -> None:
        """Take in every queued segment, then make at most ONE command check
        and ONE relevance check for the whole batch. Each check is a CLI
        call of 6-10 s while speech arrives every 2-4 s: per-segment checks
        fall further behind for as long as the meeting talks. Batching keeps
        the lag at about one cycle however much piles up."""
        new: list[Segment] = []
        for raw in batch:
            try:
                seg: Segment = (int(raw.get("seq") or 0), str(raw.get("text") or "").strip(),
                                float(raw.get("t0") or 0.0), float(raw.get("t1") or 0.0))
            except (TypeError, ValueError):
                continue
            with self._lock:
                if seg[0] <= self._last_seq or self.ended or self._ending:
                    continue
                self._last_seq = seg[0]
                self._window.append(seg)
                self._window = [s for s in self._window if s[3] >= seg[3] - WINDOW_S]
            if seg[1]:
                new.append(seg)
        if not new:
            return
        with self._lock:
            newest = new[-1]
            # The utterance to judge: the batch itself plus the speech just
            # before it (whisper splits sentences across segments).
            since = min(new[0][3], newest[3] - UTTERANCE_S)
            tail = [s for s in self._window if s[0] > self._command_seq and s[3] >= since and s[1]]
            before = "\n".join(s[1] for s in self._window if s not in tail)
            utterance = "\n".join(s[1] for s in tail)
            focus = self.focus
            states = {c: cv.state for c, cv in self.canvases.items()}
            listening = self.listening
        candidates = new
        if listening and tail and commands.PREFILTER.search(utterance):
            cmd = commands.detect(before, utterance, focus=focus, states=states)
            if cmd is not None:
                with self._lock:
                    self._command_seq = max(self._command_seq, newest[0])
                try:
                    self.apply_command(cmd, spoken=True)
                except Exception:
                    log.exception("could not apply spoken design command %s", cmd)
                # The command itself is not design talk.
                spoken = {s[0] for s in tail}
                candidates = [s for s in new if s[0] not in spoken]
        if candidates:
            self._classify(candidates)

    def _classify(self, segments: list[Segment]) -> None:
        with self._lock:
            focus = self.focus
            if focus is None or self._ending or self.canvases[focus].state != "active":
                return
            cv = self.canvases[focus]
            known = {s[0] for s in cv.heard}
            cv.heard = [s for s in cv.heard if s[0] > cv.consumed_seq] + [
                s for s in segments if s[0] > cv.consumed_seq and s[0] not in known]
            cv.heard = cv.heard[-HEARD_MAX:]
            # Judge the whole stretch since the last run, never a lone fragment.
            newest = segments[-1][3]
            stretch = [s for s in cv.heard if s[3] >= newest - JUDGE_S]
            first = stretch[0][0] if stretch else segments[0][0]
            context = "\n".join(s[1] for s in self._window if s[0] < first)
        ok, _summary = relevance.relevant(focus, "\n".join(s[1] for s in stretch or segments), context=context)
        if not ok:
            return
        with self._lock:
            cv = self.canvases[focus]
            if self.focus != focus or cv.state != "active":
                return
            held = {s[0] for s in cv.buffer.segments}
            cv.buffer.restore([s for s in cv.heard if s[0] > cv.consumed_seq and s[0] not in held])
            cv.buffer.last_at = self._clock()
        self._emit_snapshot()

    def tick(self, now: float | None = None) -> None:
        """Fire runs whose buffers are ready; expire undo tokens."""
        now = self._clock() if now is None else now
        with self._lock:
            if self.ended or self._ending:
                return
            for c, cv in self.canvases.items():
                if cv.state == "active" and cv.buffer.should_fire(now) and not self._awaiting_confirm(c):
                    self._schedule_locked(c)
            for token in [t for t, (exp, _) in self._undo.items() if exp < now]:
                del self._undo[token]

    def _awaiting_confirm(self, canvas: str) -> bool:
        return canvas == "ui" and self.ui_kind == "worktree" and not self.codebase_confirmed

    # -- run loop ----------------------------------------------------------------

    def _schedule_locked(self, canvas: str) -> None:
        if canvas not in self._pending:
            self._pending.append(canvas)
            self._cv.notify_all()

    def _worker_loop(self) -> None:
        while True:
            with self._cv:
                while not self._pending and not self._stopped:
                    self._cv.wait()
                if self._stopped:
                    return
                canvas = self._pending.pop(0)
                self._busy = True
            try:
                self._run(canvas)
            except Exception:
                log.exception("design run crashed")
            finally:
                with self._cv:
                    self._busy = False
                    self._cv.notify_all()

    def run_pending(self) -> None:
        """Run queued updates on the calling thread (unthreaded sessions)."""
        while True:
            with self._lock:
                if not self._pending:
                    return
                canvas = self._pending.pop(0)
            self._run(canvas)

    def wait_idle(self, timeout: float | None = None) -> bool:
        with self._cv:
            return self._cv.wait_for(lambda: not self._pending and not self._busy, timeout)

    def _run(self, canvas: str) -> None:
        with self._lock:
            cv = self.canvases[canvas]
            # The worktree's first run prepares the app; it needs no talk and
            # leaves the buffer for the run after it.
            bootstrap = canvas == "ui" and self.ui_kind == "worktree" and not self._bootstrapped
            if bootstrap:
                runnable = cv.state in ("active", "paused") and self.codebase is not None
            else:
                runnable = cv.state == "active" or (cv.state == "paused" and (cv.nudges or cv.build_error))
            if not runnable or self._dir is None or self._awaiting_confirm(canvas):
                return
            build_error, cv.build_error = cv.build_error, None
            segments: list[Segment] = []
            nudges: list[str] = []
            excerpt = ""
            if bootstrap:
                build_error = None
            elif build_error is None:
                excerpt, segments = cv.buffer.take()
                nudges, cv.nudges = cv.nudges, []
                if not excerpt.strip() and not nudges:
                    return
            cv.running = True
            folder = self._dir
            gen = self._codebase_gen
        self._emit_snapshot()
        try:
            if canvas == "ui":
                rev, summary = self._run_ui(folder, excerpt, nudges, build_error, gen)
            else:
                rev, summary = self._run_board(folder, excerpt, nudges)
            if canvas == "ui":
                self._check_gen(gen)
        except _Discarded:
            with self._lock:
                cv.buffer.restore(segments)
                cv.nudges = nudges + cv.nudges
        except _Unavailable as e:
            with self._lock:
                cv.state, cv.reason = "unavailable", str(e)
                cv.buffer.restore(segments)
                cv.nudges = nudges + cv.nudges
                self._persist("unavailable")
            self._publish({"type": "error", "canvas": canvas, "message": str(e)})
        except Exception as e:  # noqa: BLE001 — a failed run never ends the session
            message = str(e) or e.__class__.__name__
            log.warning("design %s run failed: %s", canvas, message)
            with self._lock:
                if canvas == "ui" and gen != self._codebase_gen:
                    # The worktree went away under the run (codebase switched).
                    cv.buffer.restore(segments)
                    cv.nudges = nudges + cv.nudges
                    return
                cv.buffer.restore(segments)
                cv.nudges = nudges + cv.nudges
                cv.failures += 1
                cv.last_error = message
                if cv.failures >= MAX_FAILURES and cv.state == "active":
                    cv.state = "paused"
                    cv.reason = f"Paused after {MAX_FAILURES} failed updates"
                self._persist("run_failed")
            self._publish({"type": "error", "canvas": canvas, "message": message})
        else:
            with self._lock:
                cv.rev = rev
                cv.revs.append({"rev": rev, "at": _now_iso(), "summary": summary})
                cv.failures = 0
                cv.last_error = None
                if build_error is None:
                    cv.fix_runs = 0
                if segments:
                    cv.consumed_seq = max(cv.consumed_seq, max(s[0] for s in segments))
                    cv.heard = [s for s in cv.heard if s[0] > cv.consumed_seq]
                if bootstrap and (cv.buffer.segments or cv.nudges):
                    self._schedule_locked("ui")
                self._persist("revision")
            self._publish({"type": "revision", "canvas": canvas, "rev": rev, "summary": summary})
            self._save_artefact()
        finally:
            with self._lock:
                cv.running = False
            self._emit_snapshot()

    def _commit(self, folder: Path, message: str) -> None:
        try:
            scaffold.commit(folder, message)
        except Exception as e:  # noqa: BLE001 — the files are written; history is best effort
            log.warning("could not commit %r in %s: %s", message, folder, e)

    def _check_gen(self, gen: int) -> None:
        with self._lock:
            if gen != self._codebase_gen:
                raise _Discarded()

    def _project_brief(self) -> str:
        """What the vault knows about the session's project ("" without one).
        Called from the worker, never under the lock: it searches the vault."""
        pid = self.project_id
        if not pid:
            return ""
        if pid not in self._briefs:
            from ghostbrain.design import project_brief

            try:
                self._briefs[pid] = project_brief.build(_lookup_project(pid))
            except Exception:  # no brief is better than no prototype
                log.exception("could not build the project brief for %s", pid)
                self._briefs[pid] = ""
        return self._briefs[pid]

    def _brief_for_ui(self) -> tuple[str, str | None]:
        """(brief to send, project id) — only when the agent's session hasn't
        had this project's brief yet (first run, or the project changed)."""
        pid = self.project_id
        if not pid or pid == self._brief_sent_for:
            return "", pid
        return self._project_brief(), pid

    def _run_ui(self, folder: Path, excerpt: str, nudges: list[str], build_error: str | None,
                gen: int) -> tuple[int, str]:
        if _provider_id() != "claude":
            raise _Unavailable(PROVIDER_REASON)
        with self._lock:
            kind, wt = self.ui_kind, self.codebase
        if kind == "worktree":
            if wt is None:
                raise _Unavailable("The app's worktree could not be restored — start a new session")
            return self._run_worktree(folder, wt, excerpt, nudges, build_error, gen)
        brief, brief_pid = self._brief_for_ui()
        result = ui_agent.run_ui(
            folder, excerpt=excerpt, nudges=nudges, pack_readme=self._pack_readme(folder),
            session_id=self.ui_session_id, budget_usd=_budget(), build_error=build_error,
            project_brief=brief, web=_web(),
        )
        summary = str(result.get("summary") or "").strip() or "Updated the prototype"
        with self._lock:
            if build_error is None:
                self._brief_sent_for = brief_pid
            self.ui_session_id = result.get("session_id") or self.ui_session_id
            rev = self.canvases["ui"].rev + 1
        self._commit(folder, f"rev {rev}: {summary}")
        return rev, summary

    def _run_worktree(self, folder: Path, wt: worktree.Worktree, excerpt: str, nudges: list[str],
                      build_error: str | None, gen: int) -> tuple[int, str]:
        with self._lock:
            bootstrap = not self._bootstrapped
            installed = self.install == "done"
            protected = self._protected
        if bootstrap:
            if not installed:
                self._install(folder, wt, gen)
            # A fixed task with no meeting text: this run may write run.json
            # and the offline mocks, nothing else that runs as code. What it
            # did to dependencies or config is undone (installed is what
            # stays installed); only the app dir's .poltergeist/ is kept.
            before = worktree.snapshot_protected(wt)
            try:
                result = ui_agent.run_ui(
                    wt.app_dir, excerpt="", nudges=[], pack_readme="", session_id=None,
                    budget_usd=_budget(), mode="bootstrap",
                )
            finally:
                restored = self._restore_after_bootstrap(wt, before)
            self._check_gen(gen)
            summary = str(result.get("summary") or "").strip() or "Prepared the app to run offline"
            if restored:
                summary += f" (kept dependencies and config unchanged: {', '.join(restored)})"
            snap = worktree.snapshot_protected(wt)
            _write_atomic(folder / "protected.json", json.dumps(snap))
            with self._lock:
                self.ui_session_id = result.get("session_id") or self.ui_session_id
                self._protected = snap
                self._bootstrapped = True
                rev = self.canvases["ui"].rev + 1
            self._commit_worktree(wt, f"rev {rev}: {summary}")
            return rev, summary

        if protected is None:
            protected = worktree.snapshot_protected(wt)
            _write_atomic(folder / "protected.json", json.dumps(protected))
            with self._lock:
                self._protected = protected
        # Meeting speech drives this run and the dev server executes
        # package.json scripts, config files and run.json: whatever the agent
        # did to them is undone, even when the run fails.
        restored: list[str] = []
        try:
            brief, brief_pid = self._brief_for_ui()
            result = ui_agent.run_ui(
                wt.app_dir, excerpt=excerpt, nudges=nudges, pack_readme="",
                session_id=self.ui_session_id, budget_usd=_budget(), build_error=build_error,
                mode="worktree", project_brief=brief, web=_web(),
            )
            if build_error is None:
                with self._lock:
                    self._brief_sent_for = brief_pid
        finally:
            restored = worktree.restore_protected(wt, protected)
            if restored:
                log.warning("reverted agent changes to protected files in %s: %s", wt.path, restored)
        self._check_gen(gen)
        summary = str(result.get("summary") or "").strip() or "Updated the app"
        if restored:
            summary += f" (kept run config unchanged: {', '.join(restored)})"
        with self._lock:
            self.ui_session_id = result.get("session_id") or self.ui_session_id
            rev = self.canvases["ui"].rev + 1
        self._commit_worktree(wt, f"rev {rev}: {summary}")
        return rev, summary

    @staticmethod
    def _restore_after_bootstrap(wt: worktree.Worktree, before: dict[str, str | None]) -> list[str]:
        """Undo the bootstrap's protected-file changes except the app dir's
        ``.poltergeist/`` (run.json); returns the paths put back."""
        app = wt.app_dir.relative_to(wt.path).as_posix()
        meta = ".poltergeist/" if app == "." else f"{app}/.poltergeist/"
        now = worktree.snapshot_protected(wt)
        target = {rel: v for rel, v in before.items() if not rel.startswith(meta)}
        target.update({rel: v for rel, v in now.items() if rel.startswith(meta)})
        restored = worktree.restore_protected(wt, target)
        if restored:
            log.warning("reverted bootstrap changes to protected files in %s: %s", wt.path, restored)
        return restored

    def _install(self, folder: Path, wt: worktree.Worktree, gen: int) -> None:
        with self._lock:
            self.install = "running"
        self._emit_snapshot()
        try:
            worktree.install(wt, log_path=folder / "install.log")
        except Exception as e:
            self._check_gen(gen)
            with self._lock:
                self.install = "failed"
            raise _Unavailable(f"Dependency install failed: {e}") from e
        with self._lock:
            self.install = "done"
            self._persist("installed")
        self._emit_snapshot()

    def _commit_worktree(self, wt: worktree.Worktree, message: str) -> None:
        try:
            # Empty too: every rev needs its commit to be revertable.
            worktree.commit(wt, message, allow_empty=True)
        except Exception as e:  # noqa: BLE001 — the files are written; history is best effort
            log.warning("could not commit %r in %s: %s", message, wt.path, e)

    def _run_board(self, folder: Path, excerpt: str, nudges: list[str]) -> tuple[int, str]:
        with self._lock:
            current = json.loads(json.dumps(self.board)) if self.board is not None else None
        result = board_agent.run_board(current, excerpt, nudges, budget_usd=_budget(),
                                       project_brief=self._project_brief())
        model = result["model"]
        summary = str(result.get("summary") or "").strip() or "Updated the board"
        with self._lock:
            rev = self.canvases["board"].rev + 1
            self._set_board(folder, rev, model)
        self._commit(folder, f"board {rev}: {summary}")
        return rev, summary

    def _set_board(self, folder: Path, rev: int, model: dict) -> None:
        _write_atomic(folder / "board.json", json.dumps(model, indent=2) + "\n")
        self.board = model
        self._board_history[rev] = model
        self._append({"kind": "board_rev", "rev": rev, "model": model})

    def _pack_readme(self, folder: Path) -> str:
        parts = []
        for name in ("README.md", "components.md"):
            try:
                parts.append((folder / "design-pack" / name).read_text(encoding="utf-8"))
            except OSError:
                continue
        return "\n\n".join(parts)

    # -- commands ------------------------------------------------------------------

    def _ui_state(self) -> dict:
        return {"focus": self.focus,
                "canvases": {c: (cv.state, cv.reason) for c, cv in self.canvases.items()}}

    def apply_command(self, cmd: Command, *, spoken: bool) -> dict | None:
        """Apply a spoken or button command; returns the ``command`` event,
        or None when nothing changed. Button commands raise SessionError."""
        # Finding a spoken codebase may take an LLM call: not under the lock.
        pick = self._resolve_hint(cmd)
        with self._lock:
            if self.ended or self._ending:
                if spoken:
                    return None
                raise SessionError("The recording has ended")
            before = self._ui_state()
            toast: dict | None = None
            try:
                if pick is _UNSET:
                    self._dispatch(cmd)
                else:
                    toast = self._dispatch_with_codebase(cmd, pick)
            except _Unavailable as e:
                self._persist("unavailable")
                canvas = cmd.canvas if cmd.canvas in CANVASES else None
                self._publish({"type": "error", "canvas": canvas, "message": str(e)})
                self._emit_snapshot()
                if spoken:
                    return None
                raise SessionError(str(e)) from e
            except SessionError:
                if spoken:
                    return None
                raise
            if toast is not None:
                self._publish({"type": "command", "command": "codebase", "canvas": "ui",
                               "label": toast, "undo_token": None, "spoken": spoken})
            if cmd.command not in ("nudge", "update") and self._ui_state() == before:
                return None
            token = None
            if cmd.command not in ("nudge", "update"):
                token = uuid.uuid4().hex
                self._undo[token] = (self._clock() + UNDO_TTL_S, before)
            event = {
                "type": "command", "command": cmd.command, "canvas": cmd.canvas,
                "label": self._label(cmd), "undo_token": token, "spoken": spoken,
            }
            self._persist(cmd.command)
            self._publish(event)
            self._emit_snapshot()
            return event

    def _resolve_hint(self, cmd: Command) -> Any:
        """The repo a spoken ``start_ui`` names (None: not found), or _UNSET
        when the hint does not apply (no hint, or the UI is already set up)."""
        if cmd.command != "start_ui" or not cmd.codebase:
            return _UNSET
        with self._lock:
            ui = self.canvases["ui"]
            if ui.rev or ui.state == "active" or self._choice is not None or self.codebase is not None:
                return _UNSET
        try:
            return codebases.resolve(cmd.codebase, codebases.scan())
        except Exception as e:  # noqa: BLE001 — not finding the repo means scratch
            log.warning("could not resolve codebase %r: %s", cmd.codebase, e)
            return None

    def _dispatch_with_codebase(self, cmd: Command, cand: codebases.Candidate | None) -> str:
        """Start the UI on the spoken repo — pending until the user confirms
        it, since installing and running it executes the repo's code — or as
        scratch when it is not found. Returns the toast label."""
        if cand is None:
            self._dispatch(cmd)
            return f"Couldn't find '{cmd.codebase}' — using a scratch prototype"
        self._switch_codebase(cand, confirmed=False)
        self._dispatch(cmd)
        return f"Use {cand.name}? Confirm in the panel"

    @staticmethod
    def _label(cmd: Command) -> str:
        if cmd.command == "start_ui":
            return "Started frontend prototype"
        if cmd.command == "start_board":
            return "Started event-storming board"
        if cmd.command in ("focus_ui", "focus_board"):
            return f"Focused on the {_NAMES[cmd.command[6:]]}"
        if cmd.command == "nudge":
            return f"Nudge: {cmd.text}"
        if cmd.command == "update":
            return f"Updating the {_NAMES.get(cmd.canvas or 'ui', 'prototype')}"
        verb = "Paused" if cmd.command == "pause" else "Resumed"
        return f"{verb} {_NAMES.get(cmd.canvas or 'both', 'design session')}"

    def _dispatch(self, cmd: Command) -> None:
        name = cmd.command
        if name in ("start_ui", "focus_ui"):
            self._activate("ui")
        elif name in ("start_board", "focus_board"):
            self._activate("board")
        elif name == "pause":
            self._pause(cmd.canvas or "both")
        elif name == "resume":
            self._resume(cmd.canvas)
        elif name == "nudge":
            self._nudge(cmd.canvas, cmd.text or "")
        elif name == "update":
            self._catch_up(cmd.canvas or self.focus, raise_if_empty=False)
        else:
            raise SessionError(f"unknown command {name!r}")

    def _activate(self, canvas: str) -> None:
        """Make ``canvas`` the active, focused one; the other pauses."""
        cv = self.canvases[canvas]
        if canvas == "ui" and _provider_id() != "claude":
            cv.state, cv.reason = "unavailable", PROVIDER_REASON
            raise _Unavailable(PROVIDER_REASON)
        pending = self._awaiting_confirm(canvas)
        try:
            # The worktree first: a repo that cannot run leaves no artefact
            # folder behind, so falling back to scratch plans a fresh one.
            # An unconfirmed repo gets neither: talk just buffers.
            if canvas == "ui" and not pending:
                self._ensure_worktree()
            if not pending:
                self._materialize()
        except _Unavailable as e:
            cv.state, cv.reason = "unavailable", str(e)
            raise
        except Exception as e:
            log.exception("could not create the prototype folder")
            reason = f"Could not create the prototype folder: {e}"
            cv.state, cv.reason = "unavailable", reason
            raise _Unavailable(reason) from e
        other = self.canvases["board" if canvas == "ui" else "ui"]
        if other.state == "active":
            other.state, other.reason = "paused", None
        cv.state, cv.reason = "active", None
        cv.failures = 0
        self.focus = canvas
        # What led up to the command is usually the first thing to build.
        # Skip talk the other canvas already used or is holding: switching
        # from the UI to the board must not model the screens just discussed.
        seen = {s[0] for s in cv.buffer.segments} | {s[0] for s in other.buffer.segments}
        floor = max(cv.consumed_seq, other.consumed_seq)
        cv.buffer.restore([s for s in self._window if s[0] > floor and s[0] not in seen])
        if pending:
            cv.reason = CONFIRM_REASON
            return
        if cv.buffer.segments:
            cv.buffer.force()
            self._schedule_locked(canvas)
        if canvas == "ui" and self.ui_kind == "worktree" and not self._bootstrapped:
            if self.install != "done":
                self.install = "running"  # shown as "Installing dependencies…" until the worker reports
            self._schedule_locked("ui")

    def _ensure_worktree(self) -> None:
        """Worktree mode: create the picked repo's worktree on first UI start."""
        if (self.ui_kind != "worktree" or self.codebase is not None or self._choice is None
                or not self.codebase_confirmed):
            return
        name = self._choice["name"]
        slug = (self._dir or self._planned).name.removeprefix(f"{self._today.isoformat()}-") or "meeting"
        try:
            wt = worktree.create(Path(self._choice["repo"]), day=self._today, slug=slug)
        except Exception as e:
            log.warning("could not create a worktree of %s: %s", self._choice["repo"], e)
            raise _Unavailable(f"Could not create a worktree of {name}: {e}") from e
        if worktree.find_app_dir(wt.path) is None:
            try:
                worktree.remove(wt)
            except Exception:
                log.exception("could not remove the worktree %s", wt.path)
            raise _Unavailable(f"No runnable frontend (package.json with a dev script) in {name}")
        self.codebase = wt
        self.install, self._bootstrapped, self._protected = "idle", False, None
        self._persist("worktree")

    def _switch_codebase(self, cand: codebases.Candidate | None, *, confirmed: bool = True) -> None:
        """Point the UI at ``cand`` (None = scratch). Only before the first UI
        rev; a worktree made for the previous choice is removed. A repo
        picked by voice is ``confirmed=False`` until set_codebase confirms it."""
        ui = self.canvases["ui"]
        if ui.rev > 0:
            raise SessionError("The prototype already has revisions — start a new session to switch codebase")
        if self.codebase is not None:
            wt, self.codebase = self.codebase, None
            try:
                worktree.remove(wt)
            except Exception:
                log.exception("could not remove the worktree %s", wt.path)
        self._codebase_gen += 1  # a run in flight for the old choice is discarded
        self._choice = {"repo": str(cand.path), "name": cand.name} if cand is not None else None
        self.ui_kind = "worktree" if cand is not None else "scratch"
        self.codebase_confirmed = confirmed or cand is None
        self.install, self._bootstrapped, self._protected = "idle", False, None
        if self._dir is None:
            self._planned = self._plan_dir()
        elif cand is None and not (self._dir / "src").is_dir():
            # The folder was made for a worktree: give it the scratch app.
            scaffold.create(self._dir, self.pack_id, title=self.recording_title or "Meeting")

    def _pause(self, target: str) -> None:
        # "Let's stop prototyping" names a canvas loosely; when the named one
        # isn't running, the speaker still means the design work that is.
        if target in CANVASES and self.canvases[target].state != "active":
            target = "both"
        for c, cv in self.canvases.items():
            if target in (c, "both") and cv.state == "active":
                cv.state, cv.reason = "paused", None

    def _resume(self, target: str | None) -> None:
        if target == "both":
            for cv in self.canvases.values():
                if cv.state == "paused":
                    cv.state, cv.reason, cv.failures = "active", None, 0
            if self.focus is None:
                self.focus = next((c for c, cv in self.canvases.items() if cv.state == "active"), None)
            return
        if target not in CANVASES:
            target = self.focus or next((c for c, cv in self.canvases.items() if cv.state == "paused"), None)
        if target is None:
            raise SessionError("Nothing to resume")
        self._activate(target)

    def _nudge(self, canvas: str | None, text: str) -> None:
        canvas = canvas or self.focus
        if canvas not in CANVASES:
            raise SessionError("Start the prototype or the board first")
        if not text.strip():
            raise SessionError("Say what to change")
        cv = self.canvases[canvas]
        if cv.state != "active":
            self._activate(canvas)
        cv.nudges.append(text.strip())
        cv.buffer.force()
        self._schedule_locked(canvas)

    # -- button entry points ----------------------------------------------------------

    def start(self, canvas: str) -> dict | None:
        return self.apply_command(Command(f"start_{canvas}", canvas, None), spoken=False)

    def pause(self, canvas: str = "both") -> dict | None:
        return self.apply_command(Command("pause", canvas, None), spoken=False)

    def resume(self, canvas: str | None = None) -> dict | None:
        return self.apply_command(Command("resume", canvas, None), spoken=False)

    def nudge(self, canvas: str | None, text: str) -> dict | None:
        with self._lock:
            target = canvas or self.focus
        return self.apply_command(Command("nudge", target, text), spoken=False)

    def force_update(self, canvas: str | None = None) -> None:
        with self._lock:
            if self.ended or self._ending:
                raise SessionError("The recording has ended")
            canvas = canvas or self.focus
            if canvas not in CANVASES or self.canvases[canvas].state not in ("active", "paused"):
                raise SessionError("Nothing to update — start the prototype or the board first")
            self._catch_up(canvas, raise_if_empty=True)

    def _catch_up(self, canvas: str | None, *, raise_if_empty: bool) -> None:
        """"Update now" (button or spoken): run on everything said since the
        last run, including speech the relevance filter let go. Caller holds
        the lock."""
        if canvas not in CANVASES or self.canvases[canvas].state not in ("active", "paused"):
            raise SessionError("Nothing to update — start the prototype or the board first")
        cv = self.canvases[canvas]
        held = {s[0] for s in cv.buffer.segments}
        seen = {s[0]: s for s in [*cv.heard, *self._window]}
        cv.buffer.restore([s for q, s in sorted(seen.items())
                           if q > cv.consumed_seq and q not in held and s[1]])
        if not cv.buffer.segments and not cv.nudges and not cv.running:
            if raise_if_empty:
                raise SessionError("Nothing new said since the last update")
            return
        cv.buffer.force()
        self._schedule_locked(canvas)

    def undo(self, token: str) -> None:
        with self._lock:
            entry = self._undo.pop(token, None)
            if entry is None or entry[0] < self._clock():
                raise SessionError("Nothing to undo")
            if self.ended or self._ending:
                raise SessionError("The recording has ended")
            before = entry[1]
            self.focus = before["focus"]
            for c, (state, reason) in before["canvases"].items():
                cv = self.canvases[c]
                cv.state, cv.reason = state, reason
                if state != "active":
                    cv.buffer.forced = False
                if state == "off":
                    cv.buffer.take()
                    cv.nudges = []
            self._persist("undo")
        self._emit_snapshot()

    def set_config(self, *, project_id: Any = _UNSET, pack_id: str | None = None) -> None:
        """Pick the project (moves the folder until the first start) and/or
        the design system (copied in, and the prototype restyled)."""
        from ghostbrain.design import packs

        with self._lock:
            if self.ended or self._ending:
                raise SessionError("The recording has ended")
            if project_id is not _UNSET:
                project = None
                if project_id:
                    project = _lookup_project(project_id)
                    if project is None:
                        raise ValueError(f"unknown project {project_id!r}")
                changed = (project["id"] if project else None) != self.project_id
                self.project_id = project["id"] if project else None
                if self._dir is None:
                    self._planned = self._plan_dir()
                    if project and project.get("design_system") and not pack_id:
                        pack_id = project["design_system"]
                elif changed and project:
                    # Picked mid-meeting: what's there was built without it.
                    ui = self.canvases["ui"]
                    if ui.state in ("active", "paused") and ui.rev > 0:
                        ui.nudges.append(
                            f"This meeting is about the project \"{project.get('name') or project['id']}\". "
                            "Rework the prototype so it is clearly built for it, using the project context.")
                        ui.buffer.force()
                        self._schedule_locked("ui")
            if pack_id and pack_id != self.pack_id:
                if packs.get_pack(pack_id) is None:
                    raise ValueError(f"unknown design system {pack_id!r}")
                self.pack_id = pack_id
                if self._dir is not None:
                    packs.copy_into(pack_id, self._dir / "design-pack")
                    ui = self.canvases["ui"]
                    if ui.state in ("active", "paused"):
                        ui.nudges.append(
                            "The design system changed: restyle the whole app with the new "
                            "design-pack/tokens.css and follow design-pack/README.md.")
                        ui.buffer.force()
                        self._schedule_locked("ui")
            self._persist("config")
        self._emit_snapshot()

    def set_codebase(self, path: str | None) -> None:
        """Build the UI on one of the scanned repos (``path``) or as a scratch
        prototype (None). Only before the first UI revision. This is the
        user's confirmation: the same path as a repo picked by voice confirms
        it, and the worktree, install and bootstrap go ahead."""
        cand = None
        if path:
            want = Path(path).expanduser().resolve()
            cand = next((c for c in codebases.scan() if Path(c.path).resolve() == want), None)
            if cand is None:
                raise ValueError(f"unknown codebase {path!r}")
        with self._lock:
            if self.ended or self._ending:
                raise SessionError("The recording has ended")
            ui = self.canvases["ui"]
            current = self._choice["repo"] if self._choice else None
            same = (str(cand.path) if cand else None) == current
            # A UI that could not run on the old choice starts on the new one.
            retry = ui.state == "unavailable" and ui.reason != PROVIDER_REASON
            confirm = same and not self.codebase_confirmed
            if same and not retry and not confirm:
                return
            restart = ui.state in ("active", "paused") or retry
            if not same:
                self._switch_codebase(cand)
            elif confirm:
                if ui.rev > 0:
                    raise SessionError("The prototype already has revisions — start a new session to switch codebase")
                self.codebase_confirmed = True
            if retry:
                ui.state, ui.reason = "off", None
            if restart:
                try:
                    self._activate("ui")
                except _Unavailable as e:
                    self._persist("unavailable")
                    self._publish({"type": "error", "canvas": "ui", "message": str(e)})
                    self._emit_snapshot()
                    raise SessionError(str(e)) from e
            self._persist("codebase")
        self._emit_snapshot()

    def report_build_error(self, rev: int, message: str) -> None:
        """The desktop could not bundle ``rev``: queue a fix run (max 2 in a row)."""
        with self._lock:
            ui = self.canvases["ui"]
            if rev != ui.rev:
                return
            message = message.strip()[:4000]
            if ui.fix_runs >= MAX_FIX_RUNS or self.ended or self._ending or ui.state not in ("active", "paused"):
                ui.last_error = message
            else:
                ui.fix_runs += 1
                ui.build_error = message
                self._schedule_locked("ui")
            self._persist("build_error")
        self._emit_snapshot()

    def revert(self, canvas: str, rev: int) -> None:
        """Make an earlier revision current again, as a new revision."""
        with self._lock:
            cv = self.canvases[canvas]
            if self._dir is None:
                raise SessionError("Nothing to revert yet")
            if cv.running:
                raise SessionError("Wait for the current update to finish")
            if rev == cv.rev or rev not in ({0} | {r["rev"] for r in cv.revs}):
                raise SessionError(f"No revision {rev} to go back to")
            new = cv.rev + 1
            summary = f"Reverted to rev {rev}"
            if canvas == "ui" and self.ui_kind == "worktree":
                if self.codebase is None:
                    raise SessionError("Nothing to revert yet")
                try:
                    worktree.revert_to(self.codebase, rev)
                except KeyError as e:
                    raise SessionError(f"Revision {rev} is not in the app's history") from e
                except Exception as e:
                    raise SessionError(f"Could not revert: {e}") from e
                self._commit_worktree(self.codebase, f"rev {new}: {summary}")
            elif canvas == "ui":
                try:
                    scaffold.revert_to(self._dir, rev)
                except KeyError as e:
                    raise SessionError(f"Revision {rev} is not in the prototype's history") from e
                self._commit(self._dir, f"rev {new}: {summary}")
            else:
                model = self._board_history.get(rev)
                if model is None:
                    raise SessionError(f"Board revision {rev} is not available")
                self._set_board(self._dir, new, json.loads(json.dumps(model)))
                self._commit(self._dir, f"board {new}: {summary}")
            cv.rev = new
            cv.revs.append({"rev": new, "at": _now_iso(), "summary": summary})
            self._persist("revert")
            self._publish({"type": "revision", "canvas": canvas, "rev": new, "summary": summary})
        self._save_artefact()
        self._emit_snapshot()

    def eject(self) -> Path:
        with self._lock:
            if self._dir is None:
                raise SessionError("Nothing to eject yet")
            if self.ui_kind == "worktree":
                raise SessionError("Only scratch prototypes can be ejected — this one is already a worktree")
            folder = self._dir
        return Path(scaffold.eject(folder))

    # -- end of recording ------------------------------------------------------------

    def end(self) -> None:
        """The recording is over: one final run per active canvas with
        buffered talk, then everything is ``ended``. Never raises."""
        try:
            with self._lock:
                if self.ended or self._ending:
                    return
                self._ending = True
                for c, cv in self.canvases.items():
                    if cv.state == "active" and (cv.buffer.segments or cv.nudges):
                        self._schedule_locked(c)
            if self._threaded:
                if not self.wait_idle(END_TIMEOUT_S):
                    log.warning("design session %s: final update still running at end", self.id)
            else:
                self.run_pending()
            with self._lock:
                for cv in self.canvases.values():
                    if cv.state in ("active", "paused"):
                        cv.state = "ended"
                self.ended = True
                self._ending = False
                self._save_artefact()
                self._persist("end")
            self._emit_snapshot()
            self._publish({"type": "end"})
        except Exception:
            log.exception("design session %s did not end cleanly", self.id)
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the session's threads (registry shutdown, end)."""
        with self._cv:
            self._stopped = True
            self._cv.notify_all()

    def _artefact_data(self) -> dict:
        """artefact.json for the folder (see ``ghostbrain.design.artefacts``).
        The meeting link is filled in by ``artefacts.link_meeting`` after
        transcription and kept here."""
        assert self._dir is not None
        try:
            existing = _load_artefact(self._dir) or {}
        except Exception:  # noqa: BLE001
            existing = {}
        ui, board = self.canvases["ui"], self.canvases["board"]
        worktree_kind = self.ui_kind == "worktree" and self.codebase is not None
        kind = "worktree" if worktree_kind else "prototype" if ui.rev else "board"
        return {
            "version": 1,
            "title": self.recording_title or existing.get("title") or "Meeting",
            "kind": kind,
            "board": board.rev > 0,
            "date": self._today.isoformat(),
            "context": self.context,
            "project": self.project_id,
            "design_system": None if worktree_kind else self.pack_id,
            "meeting": existing.get("meeting"),
            "meeting_path": existing.get("meeting_path"),
            "ui_rev": ui.rev,
            "board_rev": board.rev,
            "revs": [dict(r) for r in ui.revs],
            "codebase": self.codebase.to_dict() if worktree_kind and self.codebase else None,
            "wav": str(self.wav),
        }

    def _save_artefact(self) -> None:
        """Write the artefact note; after every revision and at the end. Never raises."""
        try:
            with self._lock:
                if self._dir is None:
                    return
                folder, data = self._dir, self._artefact_data()
            _write_artefact(folder, data)
        except Exception:
            log.exception("could not write the artefact note")

    # -- on disk ------------------------------------------------------------------------

    def _plan_dir(self) -> Path:
        from ghostbrain.paths import vault_path

        root = vault_path() / "20-contexts"
        leaf = "artefacts" if self.ui_kind == "worktree" else "prototypes"
        if self.project_id and "/" in self.project_id:
            ctx, slug = self.project_id.split("/", 1)
            base = root / ctx / "projects" / slug / leaf
        else:
            base = root / self.context / leaf
        name = _slug(self.recording_title or "") or "meeting"
        return base / f"{self._today.isoformat()}-{name}"

    def _materialize(self) -> Path:
        if self._dir is not None:
            return self._dir
        folder, n = self._planned, 2
        while folder.exists():
            folder = self._planned.with_name(f"{self._planned.name}-{n}")
            n += 1
        if self.ui_kind == "worktree":
            scaffold.init_meta(folder)  # the code lives in the worktree
        else:
            scaffold.create(folder, self.pack_id, title=self.recording_title or "Meeting")
        self._dir = folder
        self._planned = folder
        try:
            _write_atomic(pointer_path(self.wav), json.dumps(
                {"wav": str(self.wav), "prototype_dir": str(folder)}))
        except Exception:
            log.exception("could not remember the prototype folder for %s", self.wav.name)
        self._persist("created")
        return folder

    def _persist_state(self) -> dict:
        return {
            "id": self.id, "recording_title": self.recording_title, "context": self.context,
            "project_id": self.project_id, "pack_id": self.pack_id,
            "prototype_dir": str(self._dir) if self._dir else None, "focus": self.focus,
            "ui_session_id": self.ui_session_id, "ended": self.ended, "last_seq": self._last_seq,
            "today": self._today.isoformat(), "board": self.board,
            "canvases": {c: cv.persist() for c, cv in self.canvases.items()},
            "ui_kind": self.ui_kind, "codebase_choice": self._choice,
            "codebase": self.codebase.to_dict() if self.codebase else None,
            "install": self.install, "bootstrapped": self._bootstrapped,
            "codebase_confirmed": self.codebase_confirmed,
        }

    def _persist(self, event: str) -> None:
        self._append({"kind": "state", "event": event, "state": self._persist_state()})

    def _append(self, record: dict) -> None:
        if self._dir is None:
            return
        try:
            with (self._dir / "session.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": _now_iso(), **record}) + "\n")
        except Exception:
            log.exception("could not append to session.jsonl")

    @classmethod
    def restore(cls, wav: Path, folder: Path, *, listening: bool = True, threaded: bool = True,
                clock: Callable[[], float] = time.monotonic) -> DesignSession | None:
        """Rebuild a session from its ``session.jsonl`` (sidecar restart)."""
        log_path = folder / "session.jsonl"
        if not log_path.exists():
            return None
        state: dict | None = None
        history: dict[int, dict] = {}
        for line in log_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("kind") == "state" and isinstance(record.get("state"), dict):
                state = record["state"]
            elif record.get("kind") == "board_rev" and isinstance(record.get("model"), dict):
                history[int(record.get("rev", 0))] = record["model"]
        if state is None:
            return None
        try:
            today = date.fromisoformat(state.get("today") or "")
        except ValueError:
            today = None
        s = cls(
            wav, title=state.get("recording_title"), context=state.get("context") or _default_context(),
            project_id=state.get("project_id"), pack_id=state.get("pack_id"), listening=listening,
            clock=clock, threaded=threaded, today=today, session_id=state.get("id"),
        )
        with s._lock:
            s._dir = folder
            s._planned = folder
            s.focus = state.get("focus")
            s.ui_session_id = state.get("ui_session_id")
            s.board = state.get("board")
            s.ended = bool(state.get("ended"))
            s._last_seq = int(state.get("last_seq") or 0)
            s._board_history.update(history)
            if state.get("ui_kind") == "worktree":
                s.ui_kind = "worktree"
                choice = state.get("codebase_choice")
                s._choice = choice if isinstance(choice, dict) else None
                if isinstance(state.get("codebase"), dict):
                    try:
                        s.codebase = worktree.Worktree.from_dict(state["codebase"])
                    except (KeyError, TypeError, ValueError):
                        log.warning("could not restore the worktree of %s", folder)
                # An install cut short by the restart runs again.
                s.install = state.get("install") if state.get("install") in ("done", "failed") else "idle"
                s._bootstrapped = bool(state.get("bootstrapped"))
                # Sessions saved before confirmation existed made their
                # worktree only after a button pick.
                s.codebase_confirmed = bool(state.get("codebase_confirmed", s.codebase is not None))
                if s._bootstrapped:
                    try:
                        s._protected = json.loads((folder / "protected.json").read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        s._protected = None  # re-snapshotted before the next run
            for c, saved in (state.get("canvases") or {}).items():
                if c not in s.canvases:
                    continue
                cv = s.canvases[c]
                cv.state = saved.get("state") or "off"
                cv.rev = int(saved.get("rev") or 0)
                cv.reason = saved.get("reason")
                cv.last_error = saved.get("last_error")
                cv.revs = list(saved.get("revs") or [])
                cv.consumed_seq = int(saved.get("consumed_seq") or 0)
                cv.fix_runs = int(saved.get("fix_runs") or 0)
                if cv.state == "active":
                    cv.state, cv.reason = "paused", RESTART_REASON
        if s.ended:
            s.stop()
        return s


def _lookup_project(project_id: str) -> dict | None:
    from ghostbrain.api.repo import projects

    if "/" not in project_id:
        return None
    ctx, slug = project_id.split("/", 1)
    return projects.get_project(ctx, slug)


# -- registry -------------------------------------------------------------------------

_registry_lock = threading.Lock()
_sessions: dict[str, DesignSession] = {}


def _register(session: DesignSession) -> DesignSession:
    with _registry_lock:
        _sessions.pop(str(session.wav), None)
        _sessions[str(session.wav)] = session
    return session


def get(wav: Path) -> DesignSession | None:
    with _registry_lock:
        return _sessions.get(str(wav))


def current() -> DesignSession | None:
    """The most recently started session (the recording in progress, or the
    one that just ended)."""
    with _registry_lock:
        return next(reversed(_sessions.values()), None)


def _restore_for(wav: Path, *, listening: bool, threaded: bool) -> DesignSession | None:
    try:
        pointer = json.loads(pointer_path(wav).read_text(encoding="utf-8"))
        folder = Path(pointer["prototype_dir"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        return DesignSession.restore(wav, folder, listening=listening, threaded=threaded)
    except Exception:
        log.exception("could not restore the design session for %s", wav.name)
        return None


def ensure(
    wav: Path,
    *,
    title: str | None = None,
    context: str | None = None,
    project_id: str | None = None,
    pack_id: str | None = None,
    listening: bool = True,
    threaded: bool = True,
) -> DesignSession:
    """The session for ``wav``: existing, restored from disk, or new."""
    wav = Path(wav)
    existing = get(wav)
    if existing is not None:
        return existing
    session = _restore_for(wav, listening=listening, threaded=threaded) or DesignSession(
        wav, title=title, context=context or _default_context(), project_id=project_id,
        pack_id=pack_id, listening=listening, threaded=threaded,
    )
    with _registry_lock:
        if str(wav) in _sessions:
            session.stop()
            return _sessions[str(wav)]
        _sessions[str(wav)] = session
    return session


def follow(session: DesignSession, *, keepalive_s: float = 15.0) -> Iterator[dict | None]:
    """A snapshot, then every event until ``end``. Yields None every
    ``keepalive_s`` of quiet so SSE can send a heartbeat."""
    q = session.subscribe()
    try:
        yield {"type": "snapshot", "session": session.snapshot()}
        if session.ended:
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


def stop_all() -> None:
    """Forget every session and stop their threads (tests, shutdown)."""
    with _registry_lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for s in sessions:
        s.stop()
