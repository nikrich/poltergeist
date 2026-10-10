"""A5 final review: a stop or a late close must never start or kill the wrong turn.

Every /assist request owns a generation on its stream key. A stop or close that
arrives while the draft is still reading related notes (before the LLM turn is
registered) prevents that request's turn; a close from an older request never
cancels a newer request's turn on the same key.
"""
from __future__ import annotations

import threading
from unittest.mock import patch

from ghostbrain.api.repo import docs_assist
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.llm.providers import base

PLAN = "20-contexts/work/plan.md"


def _never_turn(calls: list):
    def fake(prompt, **kw):
        calls.append(kw)
        yield {"type": "done", "text": "x"}
    return fake


def _draft(**kw):
    return docs_assist.run_assist(
        path=PLAN, instruction="risks", selection=None, mode="draft",
        placement="cursor", before="# Plan", **kw,
    )


def test_a_stop_during_gather_means_the_turn_never_starts(tmp_vault, monkeypatch):
    write_note(tmp_vault, PLAN, "# Plan\n")
    gen = docs_assist.begin("j1")

    def gather_then_stop(q, current_path):
        docs_assist.cancel("j1")  # the user's stop lands while notes are read
        return "CTX"

    monkeypatch.setattr(docs_assist.docs_context, "gather", gather_then_stop)
    calls: list = []
    with patch.object(docs_assist.agent, "run_chat_turn", _never_turn(calls)):
        events = list(_draft(stream_key="j1", generation=gen))
    assert calls == []
    assert events[-1] == {"type": "error", "message": "stopped", "interrupted": True}


def test_a_close_during_gather_means_the_turn_never_starts(tmp_vault, monkeypatch):
    write_note(tmp_vault, PLAN, "# Plan\n")
    gen = docs_assist.begin("j1")

    def gather_then_close(q, current_path):
        docs_assist.close("j1", gen)  # the client went away mid-retrieval
        return "CTX"

    monkeypatch.setattr(docs_assist.docs_context, "gather", gather_then_close)
    calls: list = []
    with patch.object(docs_assist.agent, "run_chat_turn", _never_turn(calls)):
        list(_draft(stream_key="j1", generation=gen))
    assert calls == []


def test_a_superseded_request_never_starts_its_turn(tmp_vault, monkeypatch):
    write_note(tmp_vault, PLAN, "# Plan\n")
    old = docs_assist.begin("j1")

    def gather_then_rerun(q, current_path):
        docs_assist.begin("j1")  # the user re-ran on the same jot meanwhile
        return "CTX"

    monkeypatch.setattr(docs_assist.docs_context, "gather", gather_then_rerun)
    calls: list = []
    with patch.object(docs_assist.agent, "run_chat_turn", _never_turn(calls)):
        list(_draft(stream_key="j1", generation=old))
    assert calls == []
    docs_assist.cancel("j1")


def test_an_older_close_never_cancels_a_newer_turn_on_the_same_key():
    old = docs_assist.begin("j1")
    new = docs_assist.begin("j1")
    killed = threading.Event()
    base.register_turn("docs:j1", cancelled=threading.Event(), kill=killed.set)
    try:
        docs_assist.close("j1", old)  # the old stream's on_close, ~15 s late
        assert not killed.is_set()
        docs_assist.close("j1", new)
        assert killed.is_set()
    finally:
        base.unregister_turn("docs:j1")


def test_the_route_closes_only_its_own_generation(client, auth_headers):
    closers: list = []

    def fake_sse(events, *, on_close=None, **kw):
        closers.append(on_close)
        return iter([])

    def fake_run(jot_id=None, **kw):
        yield {"type": "done", "text": "x"}

    with patch("ghostbrain.api.routes.docs.sse_stream", fake_sse), \
            patch("ghostbrain.api.routes.docs.docs_assist.run_assist", fake_run):
        client.post("/v1/docs/assist", json={"jot_id": "j1"}, headers=auth_headers)
        client.post("/v1/docs/assist", json={"jot_id": "j1"}, headers=auth_headers)
    killed = threading.Event()
    base.register_turn("docs:j1", cancelled=threading.Event(), kill=killed.set)
    try:
        closers[0]()
        assert not killed.is_set()
        closers[1]()
        assert killed.is_set()
    finally:
        base.unregister_turn("docs:j1")


def test_a_finished_request_releases_its_generation(tmp_vault):
    write_note(tmp_vault, PLAN, "# Plan\n\ntext")
    gen = docs_assist.begin("inline-1")
    calls: list = []
    with patch.object(docs_assist.agent, "run_chat_turn", _never_turn(calls)):
        list(docs_assist.run_assist(
            path=PLAN, stream_key="inline-1", generation=gen,
            instruction=None, selection="text", mode="polish",
        ))
    assert len(calls) == 1
    assert "inline-1" not in docs_assist._generations
