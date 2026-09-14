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
    base.unregister_turn("conv-1"); base.unregister_turn("conv-2")
    assert base.kill_all_running() == 0
