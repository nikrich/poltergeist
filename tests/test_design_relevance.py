"""Design-talk relevance filter and update-trigger thresholds."""
from __future__ import annotations

from ghostbrain.design import relevance
from ghostbrain.design.relevance import Buffer


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def test_empty_buffer_never_fires():
    clock = Clock()
    buf = Buffer(clock=clock)
    clock.t += 100
    assert not buf.should_fire(clock())


def test_fires_after_enough_relevant_speech():
    clock = Clock()
    buf = Buffer(clock=clock)
    buf.add(1, "a list of claims with a status filter", 0.0, 12.0)
    assert not buf.should_fire(clock())
    buf.add(2, "and a detail screen", 12.0, 12.0 + relevance.FIRE_SPEECH_S - 12.0)
    assert buf.speech_s == relevance.FIRE_SPEECH_S
    assert buf.should_fire(clock())


def test_fires_after_a_pause_following_relevant_speech():
    clock = Clock()
    buf = Buffer(clock=clock)
    buf.add(1, "a login screen", 0.0, 3.0)
    clock.t += relevance.PAUSE_S - 0.5
    assert not buf.should_fire(clock())
    clock.t += 1.0
    assert buf.should_fire(clock())


def test_forced_fires_even_when_empty_and_take_clears():
    clock = Clock()
    buf = Buffer(clock=clock)
    buf.force()
    assert buf.should_fire(clock())
    buf.add(3, "x", 1.0, 2.0)
    excerpt, segs = buf.take()
    assert excerpt == "x"
    assert segs == [(3, "x", 1.0, 2.0)]
    assert buf.speech_s == 0
    assert not buf.forced
    assert not buf.should_fire(clock() + 100)


def test_restore_puts_segments_back_in_order():
    buf = Buffer(clock=Clock())
    buf.add(5, "later", 5.0, 6.0)
    buf.restore([(1, "earlier", 1.0, 2.0)])
    assert buf.take()[0] == "earlier\nlater"


def test_relevant_parses_llm_answer():
    calls = []

    class R:
        def as_json(self):
            return {"relevant": True, "summary": "claims list with filter"}

    def run(prompt, **kw):
        calls.append((prompt, kw))
        return R()

    assert relevance.relevant("ui", "show the claims in a table", run=run) == (True, "claims list with filter")
    assert calls[0][1]["model"] == "haiku"
    assert "show the claims in a table" in calls[0][0]


def test_relevant_failure_is_not_relevant():
    def boom(prompt, **kw):
        raise RuntimeError("down")
    assert relevance.relevant("board", "an order was placed", run=boom) == (False, "")


def test_relevant_prompt_carries_context_and_counts_requests_to_the_assistant():
    prompts = []

    class R:
        def as_json(self):
            return {"relevant": True, "summary": "demo the login"}

    def run(prompt, **kw):
        prompts.append(prompt)
        return R()

    relevance.relevant("ui", "now demo it to me", context="we built a login screen", run=run)
    assert "we built a login screen" in prompts[0]
    assert "demo" in prompts[0].split("now demo it to me")[1].lower()
