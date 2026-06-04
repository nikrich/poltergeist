"""Shared LLM relevance gate for noisy connectors (Outlook mail, Teams chat).

A gate is a callable ``(event) -> (relevant: bool, reason: str)``. The gate
itself wraps a single Haiku call with a JSON schema and a hard USD budget.
``apply_relevance_gate`` runs a gate over a list of events and is conservative
on error: an LLM failure keeps the event so real signal is never silently
swallowed (matching the Gmail connector's behaviour)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("ghostbrain.connectors.relevance")

Gate = Callable[[dict], "tuple[bool, str]"]

RELEVANCE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relevant", "reason"],
    "properties": {
        "relevant": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 200},
    },
}

# ~$0.06 of cache-creation overhead per `claude -p` call means a lower cap
# silently busts every check; $0.15 gives haiku headroom for one JSON reply.
DEFAULT_GATE_BUDGET_USD = 0.15


def _llm_run(prompt: str, *, model: str, json_schema: dict, budget_usd: float):
    """Indirection seam so tests can patch the LLM without importing it."""
    from ghostbrain.llm import client as llm

    return llm.run(prompt, model=model, json_schema=json_schema, budget_usd=budget_usd)


def build_llm_gate(
    *,
    prompt_path: Path,
    model: str,
    excerpt_fn: Callable[[dict], str],
    budget_usd: float = DEFAULT_GATE_BUDGET_USD,
) -> Gate:
    """Build a gate from a prompt template file. The template must contain
    ``{{content}}``; ``excerpt_fn`` renders the per-event text inserted there."""
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"missing relevance prompt {prompt_path}; re-run `ghostbrain-bootstrap`"
        )
    template = prompt_path.read_text(encoding="utf-8")

    def gate(event: dict) -> tuple[bool, str]:
        prompt = template.replace("{{content}}", excerpt_fn(event))
        result = _llm_run(
            prompt, model=model, json_schema=RELEVANCE_SCHEMA, budget_usd=budget_usd
        )
        payload = result.as_json()
        return bool(payload.get("relevant")), str(payload.get("reason") or "")

    return gate


def apply_relevance_gate(events: list[dict], gate: Gate) -> tuple[list[dict], int]:
    """Run ``gate`` over events. Returns ``(kept, dropped_count)``. On gate
    error the event is kept (conservative). Kept events get
    ``metadata.relevanceReason`` set."""
    if not events:
        return events, 0
    kept: list[dict] = []
    dropped = 0
    for ev in events:
        try:
            relevant, reason = gate(ev)
        except Exception as e:  # noqa: BLE001
            log.warning("relevance gate errored for %s: %s — keeping", ev.get("id"), e)
            kept.append(ev)
            continue
        if relevant:
            ev.setdefault("metadata", {})["relevanceReason"] = reason
            kept.append(ev)
        else:
            dropped += 1
            log.info("dropped by relevance gate id=%s reason=%s", ev.get("id"), reason)
    return kept, dropped
