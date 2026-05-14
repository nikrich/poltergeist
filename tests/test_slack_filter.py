"""Tests for the Slack LLM filter.

The LLM client is replaced with a fake callable injected via the
``_llm_run`` test seam. No subprocess, no network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ghostbrain.connectors.slack.filter import (
    BATCH_SIZE,
    FilterableMessage,
    KEEP_THRESHOLD,
    score_messages,
)
from ghostbrain.llm import client as llm


def _msg(channel: str = "engineering", sender: str = "U123", text: str = "hi") -> FilterableMessage:
    return FilterableMessage(channel=channel, sender=sender, text=text)


def _fake_run(scores_per_call: list[list[int]]):
    """Return a fake `llm.run` that yields one canned response per call."""
    state = {"i": 0}

    def fake(prompt: str, **kw: Any) -> llm.LLMResult:
        scores = scores_per_call[state["i"]]
        state["i"] += 1
        return llm.LLMResult(
            text="",
            structured={"scores": scores},
            model="haiku",
            cost_usd=0.0,
            duration_ms=10,
            session_id="fake",
            raw={},
        )

    return fake


def test_empty_input_returns_empty() -> None:
    assert score_messages([], _llm_run=_fake_run([])) == []


def test_single_batch_scores_returned_in_order() -> None:
    msgs = [_msg(text="ping me"), _msg(text="random gif"), _msg(text="urgent")]
    fake = _fake_run([[3, 0, 3]])
    assert score_messages(msgs, _llm_run=fake) == [3, 0, 3]


def test_clamping_handles_out_of_range_scores() -> None:
    msgs = [_msg(), _msg(), _msg(), _msg()]
    # Model goes off-spec: negative, too-high, string, None.
    fake = _fake_run([[-1, 99, "2", None]])
    out = score_messages(msgs, _llm_run=fake)
    assert out[0] == 0          # clamped from -1
    assert out[1] == 3          # clamped from 99
    assert out[2] == 2          # parsed from string
    assert out[3] == KEEP_THRESHOLD  # fallback for None


def test_batching_splits_at_batch_size() -> None:
    msgs = [_msg(text=str(i)) for i in range(BATCH_SIZE + 5)]
    # Two calls expected; first BATCH_SIZE all 0, second 5 all 3.
    fake = _fake_run([[0] * BATCH_SIZE, [3] * 5])
    out = score_messages(msgs, _llm_run=fake)
    assert len(out) == BATCH_SIZE + 5
    assert all(s == 0 for s in out[:BATCH_SIZE])
    assert all(s == 3 for s in out[BATCH_SIZE:])


def test_short_response_falls_back_to_keep_threshold() -> None:
    """LLM returns fewer scores than messages → keep everything in batch.

    This is the safe choice: dropping signal silently is worse than
    keeping noise the worker can re-route later.
    """
    msgs = [_msg(text="a"), _msg(text="b"), _msg(text="c")]
    fake = _fake_run([[0]])  # only one score for three messages
    out = score_messages(msgs, _llm_run=fake)
    assert out == [KEEP_THRESHOLD, KEEP_THRESHOLD, KEEP_THRESHOLD]


def test_malformed_payload_falls_back_to_keep() -> None:
    """LLM returns a wrong-shaped structured response → keep everything."""

    def bad_run(prompt: str, **kw: Any) -> llm.LLMResult:
        return llm.LLMResult(
            text="",
            structured={"not_scores": "oops"},
            model="haiku",
            cost_usd=0.0,
            duration_ms=10,
            session_id="x",
            raw={},
        )

    msgs = [_msg(), _msg()]
    out = score_messages(msgs, _llm_run=bad_run)
    assert out == [KEEP_THRESHOLD, KEEP_THRESHOLD]


def test_llm_error_falls_back_to_keep() -> None:
    """LLM errors out → keep everything in the batch."""

    def erroring_run(prompt: str, **kw: Any) -> llm.LLMResult:
        raise llm.LLMError("boom")

    msgs = [_msg(), _msg(), _msg()]
    out = score_messages(msgs, _llm_run=erroring_run)
    assert out == [KEEP_THRESHOLD] * 3
