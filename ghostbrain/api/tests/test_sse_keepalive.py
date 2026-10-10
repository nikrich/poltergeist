"""A5: SSE keepalive wrapper (undici kills a body silent for 300 s)."""
from __future__ import annotations

import json
import threading

from ghostbrain.api import sse


def test_events_pass_through_in_order():
    out = list(sse.sse_stream(iter([
        {"type": "delta", "text": "a"}, {"type": "done", "text": "a"},
    ]), keepalive_s=5))
    assert out == [
        'data: {"type": "delta", "text": "a"}\n\n',
        'data: {"type": "done", "text": "a"}\n\n',
    ]


def test_emits_keepalive_comments_while_the_turn_is_silent():
    release = threading.Event()

    def slow():
        release.wait(5)
        yield {"type": "done", "text": "ok"}

    gen = sse.sse_stream(slow(), keepalive_s=0.02)
    assert next(gen) == sse.KEEPALIVE
    assert next(gen) == sse.KEEPALIVE
    release.set()
    rest = list(gen)
    assert rest[-1] == 'data: {"type": "done", "text": "ok"}\n\n'
    assert all(x == sse.KEEPALIVE for x in rest[:-1])


def test_closing_early_calls_on_close_once():
    release = threading.Event()
    closed: list[bool] = []

    def blocked():
        release.wait(5)  # a cancelled turn ends once on_close kills it
        yield {"type": "error", "message": "interrupted", "interrupted": True}

    def on_close():
        closed.append(True)
        release.set()

    gen = sse.sse_stream(blocked(), keepalive_s=0.02, on_close=on_close)
    assert next(gen) == sse.KEEPALIVE
    gen.close()
    assert closed == [True]


def test_a_normal_finish_never_calls_on_close():
    called: list[int] = []
    list(sse.sse_stream(iter([{"type": "done", "text": ""}]), keepalive_s=5,
                        on_close=lambda: called.append(1)))
    assert called == []


def test_a_crashing_turn_becomes_an_error_event():
    def boom():
        yield {"type": "delta", "text": "a"}
        raise RuntimeError("provider exploded")

    out = list(sse.sse_stream(boom(), keepalive_s=5))
    last = json.loads(out[-1][len("data: "):])
    assert last["type"] == "error"
    assert "provider exploded" in last["message"]


def test_the_default_interval_is_read_at_call_time(monkeypatch):
    monkeypatch.setattr(sse, "KEEPALIVE_S", 0.01)
    release = threading.Event()

    def slow():
        release.wait(5)
        yield {"type": "done", "text": ""}

    gen = sse.sse_stream(slow())
    assert next(gen) == sse.KEEPALIVE
    release.set()
    list(gen)
