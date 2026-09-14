from __future__ import annotations

import threading

import pytest

from ghostbrain.llm.client import LLMError
from ghostbrain.llm.providers import base


@pytest.mark.parametrize("name,tier", [
    ("haiku", "fast"), ("sonnet", "balanced"), ("opus", "quality"),
    ("fast", "fast"), ("balanced", "balanced"), ("quality", "quality"),
    ("Sonnet", "balanced"),
])
def test_to_tier_accepts_tiers_and_claude_aliases(name, tier):
    assert base.to_tier(name) == tier


def test_to_tier_rejects_unknown():
    with pytest.raises(LLMError, match="gpt-4"):
        base.to_tier("gpt-4")


def test_turn_registry_cancel_and_kill_all():
    killed: list[str] = []
    ev = threading.Event()
    base.register_turn("conv-1", cancelled=ev, kill=lambda: killed.append("conv-1"))
    base.register_turn("conv-2", cancelled=threading.Event(), kill=lambda: killed.append("conv-2"))
    assert base.cancel_turn("conv-1") is True
    assert ev.is_set() and killed == ["conv-1"]
    assert base.cancel_turn("nope") is False
    assert base.kill_all_running() == 1          # conv-2 still registered
    assert killed == ["conv-1", "conv-2"]
    # kill_all_running clears the registry itself — no manual unregister needed.
    assert base.kill_all_running() == 0


def _raise() -> None:
    raise RuntimeError("boom")


def test_kill_all_running_continues_past_a_raising_kill():
    """One misbehaving turn's kill() must not abort reaping the rest, and the
    registry must still be cleared — a shutdown sweep can't be aborted by a
    single bad actor."""
    killed: list[str] = []
    bad_cancelled = threading.Event()
    good_cancelled = threading.Event()
    base.register_turn("bad", cancelled=bad_cancelled, kill=_raise)
    base.register_turn("good", cancelled=good_cancelled, kill=lambda: killed.append("good"))

    assert base.kill_all_running() == 2
    assert killed == ["good"]
    assert bad_cancelled.is_set() and good_cancelled.is_set()
    # Registry cleared even though "bad"'s kill() raised.
    assert base.kill_all_running() == 0
