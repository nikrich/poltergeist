"""Export a chat conversation as an LLM-summarized, auto-routed jot.

Order matters: the LLM call completes BEFORE any file is written, so a failed
export leaves no half-jot behind.
"""
from __future__ import annotations

import logging
import threading

from ghostbrain.api.repo import chat_store
from ghostbrain.api.repo.notes_manual import route_existing_jot, write_inbox_jot
from ghostbrain.llm import client as llm

log = logging.getLogger("ghostbrain.chat.export")

EXPORT_MODEL = "sonnet"
# Mirrors CHAT_BUDGET_USD in llm/agent.py — a full summary is feature-sized,
# not routing-sized, so the client's default per-call cap is too tight.
EXPORT_BUDGET_USD = 1.00
TRANSCRIPT_CHAR_CAP = 60_000  # keep the prompt bounded for marathon chats

# Busy guard: an export is a multi-second LLM call followed by file writes;
# two concurrent exports of the same conversation would write duplicate jots.
# Reject the second instead of serializing — mirrors the busy-guard pattern
# in ghostbrain/api/repo/chat.py.
_active_lock = threading.Lock()
_active: set[str] = set()


class ConversationNotFound(LookupError):
    pass


class NothingToExport(ValueError):
    pass


class ExportInProgress(RuntimeError):
    pass


PROMPT_TEMPLATE = """Summarize this chat conversation between the user and \
Poltergeist (their second-brain assistant) into a reviewable note.

Rules:
1. Markdown only. Start with a single `#` title naming the topic.
2. Sections (omit empty ones): **Summary** (2-4 sentences), **Decisions**, \
**Findings**, **Open questions**.
3. Preserve every Obsidian wikilink (`[[...]]`) from the conversation verbatim \
where relevant — they link the note back to its sources.
4. Be concrete and specific; use the user's own terminology. No filler.

Conversation transcript:

{transcript}

Note:"""


def _transcript(conv: dict) -> str:
    lines = []
    for m in conv["messages"]:
        who = "user" if m["role"] == "user" else "poltergeist"
        lines.append(f"{who}: {m['text']}")
    text = "\n\n".join(lines)
    return text[-TRANSCRIPT_CHAR_CAP:]


def export_conversation(conv_id: str) -> dict:
    with _active_lock:
        if conv_id in _active:
            raise ExportInProgress(conv_id)
        _active.add(conv_id)
    try:
        conv = chat_store.get(conv_id)
        if conv is None:
            raise ConversationNotFound(conv_id)
        if not any(m["role"] == "assistant" and m["text"] for m in conv["messages"]):
            raise NothingToExport(conv_id)

        prompt = PROMPT_TEMPLATE.format(transcript=_transcript(conv))
        # Raises LLMError on failure.
        result = llm.run(prompt, model=EXPORT_MODEL, budget_usd=EXPORT_BUDGET_USD)

        jot = write_inbox_jot(
            result.text.strip() + "\n",
            extra={
                "source": "chat-summary",
                "chat_id": conv_id,
                "chat_title": conv["title"],
            },
        )
        routed = route_existing_jot(jot["id"])
        return {
            "jot_id": jot["id"],
            "path": routed.get("path", jot["path"]),
            "routingStatus": routed.get("routingStatus", "manual_review"),
            "context": routed.get("context"),
            "project": routed.get("project"),
            "title": conv["title"],
        }
    finally:
        with _active_lock:
            _active.discard(conv_id)
