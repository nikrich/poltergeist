"""Chat turn orchestration: stream agent events, persist as a side effect.

Generator-of-dicts all the way down: the route turns these into SSE lines.
If a stale ``--resume`` is rejected we retry ONCE without a session, stuffing
the recent transcript into the prompt so conversational context survives.
"""
from __future__ import annotations

import logging
import threading
from typing import Iterator

from ghostbrain.api.repo import chat_store
from ghostbrain.llm import agent

log = logging.getLogger("ghostbrain.chat")

HISTORY_FALLBACK_MESSAGES = 6

# Busy guard: each send_message loads its own dict copy of the conversation,
# so two concurrent turns would clobber each other's messages (last writer
# wins). Reject a second in-flight turn instead of serializing. The desktop
# UI disables the composer mid-turn — this is defense-in-depth for the API.
_active_lock = threading.Lock()
_active: set[str] = set()


def send_message(conv_id: str, text: str) -> Iterator[dict]:
    with _active_lock:
        if conv_id in _active:
            yield {
                "type": "error",
                "message": "a turn is already in progress for this conversation",
            }
            return
        _active.add(conv_id)
    try:
        conv = chat_store.get(conv_id)
        if conv is None:
            yield {"type": "error", "message": "conversation not found"}
            return
        chat_store.append_user_message(conv, text)
        session_id = conv.get("claude_session_id")
        try:
            yield from _stream_turn(conv, text, session_id)
        except agent.ResumeFailed as e:
            log.warning(
                "resume failed for %s (%s); retrying without session", conv_id, e
            )
            yield from _stream_turn(conv, _with_history(conv, text), None)
    finally:
        with _active_lock:
            _active.discard(conv_id)


def _with_history(conv: dict, text: str) -> str:
    """Fallback prompt for a fresh session: recent transcript + the new turn.

    ``messages[-1]`` is the just-appended user message — exclude it, then take
    the HISTORY_FALLBACK_MESSAGES before it.
    """
    recent = conv["messages"][-(HISTORY_FALLBACK_MESSAGES + 1) : -1]
    lines = [f"{m['role']}: {m['text']}" for m in recent]
    return (
        "Earlier in this conversation (your session was reset — this is the "
        "transcript):\n\n" + "\n\n".join(lines) + f"\n\nuser: {text}"
    )


def _stream_turn(conv: dict, prompt: str, session_id: str | None) -> Iterator[dict]:
    parts: list[str] = []
    tools: list[dict] = []
    for event in agent.run_chat_turn(prompt, session_id=session_id):
        if event["type"] == "session":
            chat_store.set_session_id(conv, event["session_id"])
        elif event["type"] == "delta":
            parts.append(event["text"])
        elif event["type"] == "tool":
            tools.append({"name": event["name"], "summary": event["summary"]})
        elif event["type"] == "done":
            if event.get("session_id"):
                chat_store.set_session_id(conv, event["session_id"])
            # Prefer the result's full text; fall back to assembled deltas.
            chat_store.append_assistant_message(
                conv, event["text"] or "".join(parts), tools
            )
        elif event["type"] == "error":
            partial = "".join(parts)
            if partial:
                chat_store.append_assistant_message(
                    conv, partial, tools, interrupted=True
                )
        yield event
