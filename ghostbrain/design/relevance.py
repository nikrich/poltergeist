"""Design-talk filter and update triggers for an active canvas.

New transcript text is classified as relevant to the focused canvas (or
dropped); relevant segments collect in that canvas's :class:`Buffer` until
enough speech has piled up, the speakers paused after it, or a nudge /
"Update now" forces a run.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger("ghostbrain.design.relevance")

FIRE_SPEECH_S = 20.0  # relevant speech that triggers an update on its own
PAUSE_S = 6.0         # quiet after relevant speech that triggers an update

Segment = tuple[int, str, float, float]  # (seq, text, start_s, end_s)

SCHEMA: dict = {
    "type": "object",
    "properties": {"relevant": {"type": "boolean"}, "summary": {"type": "string"}},
    "required": ["relevant", "summary"],
    "additionalProperties": False,
}

_TOPICS = {
    "ui": "the frontend being prototyped: screens, pages, navigation, forms, fields, "
          "tables, buttons, user flows, validation, layout or visual details",
    "board": "the backend/domain being modelled: business events, commands, rules, "
             "policies, aggregates, data, integrations, external systems, actors or open questions",
}

PROMPT = """Earlier in the meeting (context only):
{context}

New transcript excerpt (speech-to-text, may be rough):
{text}

Does the new excerpt say anything about {topic}? Read it in the light of the
earlier context: "show me that", "fill it in", "demo it" or "make it bigger"
are about the prototype when the conversation is. Requests to the design
assistant to change, show or demo the prototype are relevant.
Small talk, scheduling and unrelated discussion are not relevant.
Answer as JSON: {{"relevant": true|false, "summary": "<one line: the design-relevant content, or empty>"}}"""


class Buffer:
    """Relevant segments waiting for the next run of one canvas."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.segments: list[Segment] = []
        self.last_at: float | None = None
        self.forced = False

    @property
    def speech_s(self) -> float:
        return sum(max(0.0, end - start) for _, _, start, end in self.segments)

    def add(self, seq: int, text: str, start: float, end: float) -> None:
        self.segments.append((seq, text, start, end))
        self.last_at = self._clock()

    def restore(self, segments: list[Segment]) -> None:
        """Put back the segments of a failed run, ahead of newer ones."""
        if segments:
            self.segments = sorted([*segments, *self.segments], key=lambda s: s[0])
            self.last_at = self.last_at or self._clock()

    def force(self) -> None:
        self.forced = True

    def should_fire(self, now: float) -> bool:
        if self.forced:
            return True
        if not self.segments:
            return False
        if self.speech_s >= FIRE_SPEECH_S:
            return True
        return self.last_at is not None and now - self.last_at >= PAUSE_S

    def take(self) -> tuple[str, list[Segment]]:
        segments, self.segments = self.segments, []
        self.forced = False
        self.last_at = None
        return "\n".join(text for _, text, _, _ in segments), segments


def _default_run(prompt: str, **kw: Any) -> Any:
    from ghostbrain.llm import client

    return client.run(prompt, **kw)


def relevant(
    canvas: str, text: str, *, context: str = "", run: Callable[..., Any] | None = None,
) -> tuple[bool, str]:
    """Whether ``text`` matters to ``canvas``, plus a one-line summary.
    Failure counts as not relevant."""
    if not text.strip():
        return False, ""
    prompt = PROMPT.format(text=text.strip(), context=context.strip() or "(none)",
                           topic=_TOPICS.get(canvas, _TOPICS["ui"]))
    try:
        data = (run or _default_run)(prompt, model="haiku", json_schema=SCHEMA, timeout_s=60).as_json()
    except Exception as e:  # noqa: BLE001 — never let the filter break the listener
        log.warning("design relevance check failed: %s", e)
        return False, ""
    if not isinstance(data, dict):
        return False, ""
    return bool(data.get("relevant")), str(data.get("summary") or "")
