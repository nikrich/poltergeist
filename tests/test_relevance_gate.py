"""Tests for the shared relevance gate. The LLM client is mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_apply_gate_keeps_relevant_and_drops_irrelevant() -> None:
    from ghostbrain.connectors._relevance import apply_relevance_gate

    events = [{"id": "1"}, {"id": "2"}]

    def fake_gate(ev):
        return (ev["id"] == "1", "because")

    kept, dropped = apply_relevance_gate(events, fake_gate)
    assert [e["id"] for e in kept] == ["1"]
    assert dropped == 1
    assert kept[0]["metadata"]["relevanceReason"] == "because"


def test_apply_gate_keeps_event_on_gate_error() -> None:
    from ghostbrain.connectors._relevance import apply_relevance_gate

    def boom(ev):
        raise RuntimeError("llm down")

    kept, dropped = apply_relevance_gate([{"id": "1"}], boom)
    assert [e["id"] for e in kept] == ["1"]  # conservative: kept
    assert dropped == 0


def test_apply_gate_empty_is_noop() -> None:
    from ghostbrain.connectors._relevance import apply_relevance_gate

    kept, dropped = apply_relevance_gate([], lambda ev: (True, ""))
    assert kept == []
    assert dropped == 0


def test_build_gate_parses_llm_json(tmp_path, monkeypatch) -> None:
    from ghostbrain.connectors import _relevance

    prompt = tmp_path / "p.md"
    prompt.write_text("Decide: {{content}}", encoding="utf-8")

    fake_result = MagicMock()
    fake_result.as_json.return_value = {"relevant": True, "reason": "ok"}

    with patch.object(_relevance, "_llm_run", return_value=fake_result) as run:
        gate = _relevance.build_llm_gate(
            prompt_path=prompt,
            model="haiku",
            excerpt_fn=lambda ev: f"X{ev['id']}",
        )
        relevant, reason = gate({"id": "9"})

    assert relevant is True
    assert reason == "ok"
    # Prompt template had {{content}} substituted with the excerpt.
    sent_prompt = run.call_args.args[0]
    assert "X9" in sent_prompt
    assert "{{content}}" not in sent_prompt
