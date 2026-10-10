"""Docs assistant: one-shot streamed writing turns over a jot.

Unlike chat there is no session persistence — every assist call is a fresh
single turn. Cancellation reuses the agent registry with key ``docs:<stream key>``
(stream_id, else jot id, else "path:<path>").

Each request also owns a generation on its key (``begin``). A draft reads
related notes before its turn registers, so a stop in that window has no turn
to kill: the generation carries the stop instead, and ``run_assist`` never
starts the turn. A request's own ``close`` (the SSE on_close, which can fire
seconds late) only cancels the turn while it is still the key's current
request, so it can't kill a newer run on the same jot.
"""
from __future__ import annotations

import logging
import threading
from typing import Iterator

from ghostbrain.api.repo import docs_context, notes_manual
from ghostbrain.api.repo import note as note_repo
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

BEFORE_CAP = 8000  # spec: continue sends the text before the cursor, capped at 8k chars

CANNED_INSTRUCTIONS = {
    "draft": "Write the document described by the user's instruction.",
    "polish": "Polish this text: fix grammar, tighten wording, improve flow. Preserve meaning, structure, and markdown formatting.",
    "expand": "Expand this text with relevant detail, grounded in the vault where possible. Keep the existing structure and voice.",
    "summarize": "Rewrite this text as a tighter summary, preserving the key points and any headings worth keeping.",
    "continue": "Continue writing from exactly where the text before the cursor stops. Keep the same voice, language and formatting. Write at most three paragraphs.",
    "translate": "Translate this text into {language}. Keep the meaning, tone and markdown structure.",
}

# Inline edits land inside A1's blocks, which live in markdown as plain-text
# conventions. A model that "tidies" them breaks the block on the next open.
BLOCK_SYNTAX_RULES = """Keep Poltergeist's block syntax exactly as written:
- callout headers such as `> [!info] Title` (keep the `[!kind]` marker and any `-`/`+` after it; the title may change);
- status lozenges such as `status:In progress/yellow` inside backticks (keep `status:` and `/colour`; the label may change);
- ```toc and ```mermaid fences (copy them unchanged);
- images such as `![alt|480](path)` (keep the path and the width);
- wikilinks such as `[[path|Alias]]` (keep the path; the alias may change)."""


def _task(mode: str, target_language: str | None) -> str:
    task = CANNED_INSTRUCTIONS.get(mode, CANNED_INSTRUCTIONS["polish"])
    if mode == "translate":
        task = task.format(language=target_language or "English")
    return task


def build_prompt(
    *,
    body: str,
    instruction: str | None,
    selection: str | None,
    mode: str,
    target_language: str | None = None,
    before: str | None = None,
    placement: str | None = None,
    vault_context: str | None = None,
) -> str:
    parts = [f"Task: {_task(mode, target_language)}"]
    if instruction:
        parts.append(f"User instruction: {instruction}")
    if vault_context:
        parts.append(
            "VAULT NOTES (retrieved for this request; ground claims in them):\n"
            + vault_context
        )
    where = "cursor" if mode == "continue" else (placement or ("selection" if selection else "doc"))
    if where == "cursor":
        tail = (before or "")[-BEFORE_CAP:]
        parts.append(
            "Reply with ONLY the new markdown to insert at the cursor. "
            "Do not repeat any of the existing text."
        )
        parts.append(BLOCK_SYNTAX_RULES)
        if mode != "continue" and body.strip():
            parts.append(f"FULL DOCUMENT (context only):\n{body}")
        parts.append(
            f"TEXT BEFORE THE CURSOR:\n{tail}" if tail.strip()
            else "The cursor is at the start of the document."
        )
    elif where == "selection" and selection:
        parts.append(
            "The user selected part of the document. Reply with ONLY the "
            "replacement markdown for the SELECTION."
        )
        parts.append(BLOCK_SYNTAX_RULES)
        parts.append(f"FULL DOCUMENT (context only):\n{body}")
        parts.append(f"SELECTION (replace this):\n{selection}")
    else:
        parts.append(
            "Reply with ONLY the full replacement document as markdown."
        )
        parts.append(f"CURRENT DOCUMENT:\n{body}" if body.strip() else "The document is currently empty.")
    return "\n\n".join(parts)


class _TargetError(Exception):
    pass


def _resolve_target(jot_id: str | None, path: str | None) -> tuple[str, str]:
    """(body, vault-relative path) of the note being assisted."""
    if jot_id is not None:
        try:
            jot = notes_manual.read_jot(jot_id)
        except notes_manual.JotNotFound:
            raise _TargetError("jot not found") from None
        # notes_manual builds the path with str(Path), so backslashes on Windows.
        return jot["body"], jot["path"].replace("\\", "/")
    if not path:
        raise _TargetError("send a jot_id or a path")
    try:
        found = note_repo.get_note(path)
    except note_repo.NoteInvalidPath:
        raise _TargetError("invalid note path") from None
    except note_repo.NoteNotFound:
        raise _TargetError("note not found") from None
    return found["body"], path


class Generation:
    """One /assist request's claim on its stream key."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()


_gen_lock = threading.Lock()
_generations: dict[str, Generation] = {}


def begin(key: str) -> Generation:
    """Make a new request the key's current one; an older one is superseded."""
    gen = Generation()
    with _gen_lock:
        old = _generations.get(key)
        _generations[key] = gen
    if old is not None:
        old.cancelled.set()
    return gen


def _release(key: str, gen: Generation) -> None:
    with _gen_lock:
        if _generations.get(key) is gen:
            del _generations[key]


def run_assist(
    jot_id: str | None = None,
    *,
    path: str | None = None,
    stream_key: str | None = None,
    instruction: str | None,
    selection: str | None,
    mode: str,
    target_language: str | None = None,
    before: str | None = None,
    placement: str | None = None,
    generation: Generation | None = None,
) -> Iterator[dict]:
    key = stream_key or jot_id or f"path:{path}"
    gen = generation or begin(key)
    try:
        yield from _run(
            jot_id, path=path, key=key, gen=gen, instruction=instruction,
            selection=selection, mode=mode, target_language=target_language,
            before=before, placement=placement,
        )
    finally:
        _release(key, gen)


def _run(
    jot_id: str | None,
    *,
    path: str | None,
    key: str,
    gen: Generation,
    instruction: str | None,
    selection: str | None,
    mode: str,
    target_language: str | None,
    before: str | None,
    placement: str | None,
) -> Iterator[dict]:
    try:
        body, rel = _resolve_target(jot_id, path)
    except _TargetError as e:
        yield {"type": "error", "message": str(e)}
        return
    vault_context: str | None = None
    if mode == "draft":
        yield {"type": "tool", "name": "vault_context", "summary": "reading related notes"}
        vault_context = docs_context.gather(instruction or selection or "", current_path=rel) or None
    prompt = build_prompt(
        body=body,
        instruction=instruction,
        selection=selection,
        mode=mode,
        target_language=target_language,
        before=before,
        placement=placement,
        vault_context=vault_context,
    )
    if gen.cancelled.is_set():  # stopped, closed or superseded while gathering
        yield {"type": "error", "message": "stopped", "interrupted": True}
        return
    yield from agent.run_chat_turn(
        prompt,
        system_prompt=DOCS_SYSTEM_PROMPT,
        allowed_tools=DOCS_ALLOWED_TOOLS,
        turn_key=f"docs:{key}",
    )


def cancel(key: str) -> bool:
    """Stop whatever runs on ``key``, including a request still gathering."""
    with _gen_lock:
        gen = _generations.pop(key, None)
    if gen is not None:
        gen.cancelled.set()
    return agent.cancel_turn(f"docs:{key}") or gen is not None


def close(key: str, gen: Generation) -> None:
    """One request's stream went away: stop it, and its turn only if current."""
    gen.cancelled.set()
    with _gen_lock:
        if _generations.get(key) is not gen:
            return  # superseded: the registered turn belongs to a newer request
        del _generations[key]
        agent.cancel_turn(f"docs:{key}")
