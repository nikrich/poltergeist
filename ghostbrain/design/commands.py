"""Spoken-command detection for the live design session.

A cheap regex prefilter runs on every new transcript segment; only a match
pays for a fast-tier LLM call that decides whether the speaker actually
directed the meeting ("let's kick off a frontend prototype") or just used
one of the words. Failures return None — a missed command is harmless, a
crash in the listener is not.
"""
from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Callable
from typing import Any

log = logging.getLogger("ghostbrain.design.commands")

PREFILTER = re.compile(
    r"\b(?:"
    r"prototyp\w*|front[\s-]?ends?|ui|screens?|mock[\s-]?ups?|wireframes?"
    r"|back[\s-]?ends?|event[\s-]?storm\w*|domain|design\w*"
    r"|stop\w*|park\w*|paus\w*|resum\w*|pick(?:\s+\S+){0,4}\s+back\s+up"
    r"|switch\w*|focus\w*|let[’']?s|updat\w*|refresh\w*"
    r"|existing|repo\w*|codebase|extend\w*"
    r")\b",
    re.IGNORECASE,
)

COMMANDS = ("start_ui", "start_board", "focus_ui", "focus_board", "pause", "resume", "nudge", "update")

SCHEMA: dict = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "enum": [*COMMANDS, "none"]},
        "canvas": {"type": ["string", "null"], "enum": ["ui", "board", "both", None]},
        "text": {"type": ["string", "null"]},
        "codebase": {"type": ["string", "null"]},
    },
    "required": ["command", "canvas", "text", "codebase"],
    "additionalProperties": False,
}

PROMPT = """You listen to a live meeting transcript and detect explicit instructions
that direct a live design assistant. The assistant has two canvases:
- "ui": a working frontend prototype (screens, forms, flows)
- "board": an event-storming board of the backend/domain

Commands:
- start_ui: someone explicitly starts frontend prototyping ("let's kick off a frontend prototype", "let's mock up the screens")
- start_board: someone explicitly starts backend/domain modelling ("let's event-storm this", "let's map out the backend")
- focus_ui / focus_board: someone moves the discussion to that canvas ("let's focus on the backend now", "back to the UI")
- pause: someone stops or parks design work ("let's stop prototyping", "park the design stuff"); canvas = "both" unless they clearly name only one ("pause the board", "stop the UI prototype but keep the board going") — generic words like prototyping/design/mocking mean "both"
- resume: someone picks it back up ("let's pick the prototype back up")
- nudge: an explicit instruction aimed at the prototype or board ("make that table sortable", "add a filter", "add a payment-failed event"); text = the instruction, rewritten as a short imperative. Only when a canvas is active.
- codebase: when start_ui asks to build on an existing app/frontend/repo ("today we're working on Atlas, use our existing frontend"), the name of that app as spoken ("Atlas frontend"); otherwise null. Only for start_ui.
- update: someone asks the assistant to apply what was discussed now, or complains it isn't updating ("please do the update as we discussed", "update it", "show me that", "why aren't you updating?"). canvas = the one named, else null.
- none: everything else — discussion, small talk, or words like "design" or "screen" mentioned without anyone wanting the assistant to act.

This is speech-to-text, so judge intent, not wording:
- A sentence is often split over lines ("let's start a design session" / "a front-end prototype."); read the NEW lines together as one utterance.
- Questions and requests to the assistant count ("are you going to start the front end prototype?", "can you show the backend?").
- The assistant is called Poltergeist and is often misheard ("Polter guys", "poultry guys"); "design set" may be "design session".
- "Start a design session" with no canvas named means start_ui.

Current state: focus={focus}; canvases={states}

Earlier transcript (context only — commands in it were already handled):
{window}

NEW transcript (decide only on this; it may be several lines of one utterance):
{new}

Answer as JSON: {{"command": ..., "canvas": "ui"|"board"|"both"|null, "text": string|null, "codebase": string|null}}"""

_DEFAULT_CANVAS = {
    "start_ui": "ui", "focus_ui": "ui", "start_board": "board", "focus_board": "board",
}


@dataclasses.dataclass(frozen=True)
class Command:
    command: str
    canvas: str | None
    text: str | None
    # start_ui only: the existing app to build on, as spoken ("Atlas frontend").
    codebase: str | None = None


def _default_run(prompt: str, **kw: Any) -> Any:
    from ghostbrain.llm import client

    return client.run(prompt, **kw)


def detect(
    window_text: str,
    new_text: str,
    *,
    focus: str | None,
    states: dict[str, str],
    run: Callable[..., Any] | None = None,
) -> Command | None:
    """The command spoken in ``new_text``, or None. Never raises."""
    if not new_text.strip() or not PREFILTER.search(new_text):
        return None
    prompt = PROMPT.format(
        focus=focus or "none",
        states=", ".join(f"{k}={v}" for k, v in sorted(states.items())) or "all off",
        window=window_text.strip() or "(none)",
        new=new_text.strip(),
    )
    try:
        data = (run or _default_run)(prompt, model="haiku", json_schema=SCHEMA, timeout_s=60).as_json()
    except Exception as e:  # noqa: BLE001 — never let detection break the listener
        log.warning("design command detection failed: %s", e)
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("command")
    if name not in COMMANDS:
        return None
    canvas = data.get("canvas")
    canvas = canvas if canvas in ("ui", "board", "both") else None
    text = data.get("text") if isinstance(data.get("text"), str) else None
    if name in _DEFAULT_CANVAS:
        canvas = _DEFAULT_CANVAS[name]
    elif name == "update":
        canvas = canvas if canvas in ("ui", "board") else focus
        if canvas is None or states.get(canvas) not in ("active", "paused"):
            return None
    elif name in ("pause", "resume") and canvas is None:
        canvas = "both" if name == "pause" else focus
    elif name == "nudge":
        canvas = canvas if canvas in ("ui", "board") else focus
        if not text or not text.strip():
            return None
        if canvas is None or states.get(canvas) not in ("active", "paused"):
            return None
        text = text.strip()
    codebase = data.get("codebase") if name == "start_ui" and isinstance(data.get("codebase"), str) else None
    return Command(name, canvas, text if name == "nudge" else None, (codebase or "").strip()[:120] or None)
