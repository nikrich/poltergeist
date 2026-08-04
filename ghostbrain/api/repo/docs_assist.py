"""Docs assistant: one-shot streamed writing turns over a jot.

Unlike chat there is no session persistence — every assist call is a fresh
single turn. Cancellation reuses the agent registry with key ``docs:<jot_id>``.
"""
from __future__ import annotations

import logging
from typing import Iterator

from ghostbrain.api.repo import notes_manual
from ghostbrain.llm import agent

log = logging.getLogger("ghostbrain.docs_assist")

DOCS_ALLOWED_TOOLS = ",".join(
    n for n in agent.TOOL_SUMMARIES if not n.endswith("poltergeist_ask")
)

DOCS_SYSTEM_PROMPT = """You are Poltergeist's technical writer. You draft and \
polish documents inside the user's personal knowledge app, grounded in their \
vault.

Rules:
1. Ground factual claims in the vault: poltergeist_search to locate notes, \
poltergeist_get_note to read them. Never invent facts about the user's work; \
if the vault doesn't cover something, write around it or mark it [TODO].
2. Your ENTIRE output is used verbatim as document content. Output ONLY \
markdown for the document — no preamble, no explanation, no code fences \
around the whole answer, no YAML frontmatter.
3. Match the user's tone and terminology. Keep structure clean: one H1 at \
most, sensible heading levels, tight prose."""

CANNED_INSTRUCTIONS = {
    "draft": "Write the document described by the user's instruction.",
    "polish": "Polish this text: fix grammar, tighten wording, improve flow. Preserve meaning, structure, and markdown formatting.",
    "expand": "Expand this text with relevant detail, grounded in the vault where possible. Keep the existing structure and voice.",
    "summarize": "Rewrite this text as a tighter summary, preserving the key points and any headings worth keeping.",
}


def build_prompt(
    *, body: str, instruction: str | None, selection: str | None, mode: str
) -> str:
    task = CANNED_INSTRUCTIONS.get(mode, CANNED_INSTRUCTIONS["polish"])
    parts = [f"Task: {task}"]
    if instruction:
        parts.append(f"User instruction: {instruction}")
    if selection:
        parts.append(
            "The user selected part of the document. Reply with ONLY the "
            "replacement markdown for the SELECTION."
        )
        parts.append(f"FULL DOCUMENT (context only):\n{body}")
        parts.append(f"SELECTION (replace this):\n{selection}")
    else:
        parts.append(
            "Reply with ONLY the full replacement document as markdown."
        )
        parts.append(f"CURRENT DOCUMENT:\n{body}" if body.strip() else "The document is currently empty.")
    return "\n\n".join(parts)


def run_assist(
    jot_id: str, *, instruction: str | None, selection: str | None, mode: str
) -> Iterator[dict]:
    try:
        jot = notes_manual.read_jot(jot_id)
    except notes_manual.JotNotFound:
        yield {"type": "error", "message": "jot not found"}
        return
    prompt = build_prompt(
        body=jot["body"], instruction=instruction, selection=selection, mode=mode
    )
    yield from agent.run_chat_turn(
        prompt,
        system_prompt=DOCS_SYSTEM_PROMPT,
        allowed_tools=DOCS_ALLOWED_TOOLS,
        turn_key=f"docs:{jot_id}",
    )


def cancel(jot_id: str) -> bool:
    return agent.cancel_turn(f"docs:{jot_id}")
