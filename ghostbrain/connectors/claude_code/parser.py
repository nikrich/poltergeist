"""Parse a Claude Code session JSONL transcript into a digest the worker can
route, summarize, and store.

Sessions can run to tens of MB. We stream the file, skip non-message events,
and produce a compact summary: first N user prompts (sets the topic) plus the
last few exchanges (captures the resolution).
"""

from __future__ import annotations

import dataclasses
import json
import logging
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger("ghostbrain.connectors.claude_code.parser")

DEFAULT_HEAD_USER_TURNS = 3
DEFAULT_TAIL_TURNS = 4
DEFAULT_TURN_CHAR_LIMIT = 4_000


@dataclasses.dataclass
class SessionTurn:
    role: str  # "user" or "assistant"
    text: str
    timestamp: str | None  # ISO8601 if available

    def truncated(self, limit: int) -> "SessionTurn":
        if len(self.text) <= limit:
            return self
        head = self.text[: limit // 2]
        tail = self.text[-limit // 2 :]
        return SessionTurn(
            role=self.role,
            text=f"{head}\n\n[…truncated {len(self.text) - limit} chars…]\n\n{tail}",
            timestamp=self.timestamp,
        )


@dataclasses.dataclass
class SessionDigest:
    """What the pipeline gets to work with."""

    session_id: str
    cwd: str | None
    started_at: str | None
    ended_at: str | None
    user_turn_count: int
    assistant_turn_count: int
    head: list[SessionTurn]  # first N user turns
    tail: list[SessionTurn]  # last K turns of either role
    transcript_path: str

    def as_excerpt(self, *, turn_char_limit: int = DEFAULT_TURN_CHAR_LIMIT) -> str:
        """Render head + tail as plain text for an LLM prompt."""
        parts: list[str] = []
        if self.head:
            parts.append("=== Opening prompts ===")
            for t in self.head:
                t = t.truncated(turn_char_limit)
                parts.append(f"[{t.role}] {t.text}")
        if self.tail:
            parts.append("\n=== Final exchanges ===")
            for t in self.tail:
                t = t.truncated(turn_char_limit)
                parts.append(f"[{t.role}] {t.text}")
        return "\n\n".join(parts)


def parse_transcript(
    path: Path,
    *,
    head_user_turns: int = DEFAULT_HEAD_USER_TURNS,
    tail_turns: int = DEFAULT_TAIL_TURNS,
) -> SessionDigest:
    """Stream-parse a session JSONL and return a digest."""
    head: list[SessionTurn] = []
    tail: deque[SessionTurn] = deque(maxlen=tail_turns)
    user_turn_count = 0
    assistant_turn_count = 0
    session_id = ""
    started_at: str | None = None
    ended_at: str | None = None

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log.warning("malformed JSONL at %s:%d, skipping", path, line_no)
                continue

            session_id = event.get("sessionId") or session_id
            ts = event.get("timestamp")
            if ts:
                if started_at is None:
                    started_at = ts
                ended_at = ts

            t = event.get("type")
            if t not in ("user", "assistant"):
                continue

            text = _extract_text(event.get("message", {}))
            if not text:
                continue

            turn = SessionTurn(role=t, text=text, timestamp=ts)
            if t == "user":
                user_turn_count += 1
                if len(head) < head_user_turns:
                    head.append(turn)
            else:
                assistant_turn_count += 1
            tail.append(turn)

    return SessionDigest(
        session_id=session_id,
        cwd=None,  # filled in by the caller from the hook payload
        started_at=started_at,
        ended_at=ended_at,
        user_turn_count=user_turn_count,
        assistant_turn_count=assistant_turn_count,
        head=head,
        tail=list(tail),
        transcript_path=str(path),
    )


def _extract_text(message: dict[str, Any]) -> str:
    """Pull human-readable text out of a message. Skips tool_use/tool_result/thinking."""
    content = message.get("content")
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text")
            if isinstance(t, str) and t.strip():
                parts.append(t.strip())
        elif btype == "tool_result":
            inner = block.get("content")
            # Tool results are noisy but a one-line summary helps the router.
            summary = _summarize_tool_result(inner)
            if summary:
                parts.append(f"[tool_result] {summary}")
    return "\n".join(parts).strip()


def _summarize_tool_result(content: Any) -> str:
    if isinstance(content, str):
        first_line = content.splitlines()[0] if content else ""
        return first_line[:200]
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if t:
                    return t.splitlines()[0][:200] if t.splitlines() else ""
    return ""


def derive_cwd_from_dirname(transcript_path: Path) -> str | None:
    """Best-effort decode of the encoded cwd from the parent directory name.

    Claude Code writes sessions to ``~/.claude/projects/<encoded-cwd>/<id>.jsonl``
    where ``/`` is replaced with ``-``. The encoding is lossy when the original
    path contained hyphens, so this is only a fallback — prefer the ``cwd``
    field from the hook payload when available.
    """
    encoded = transcript_path.parent.name
    if not encoded.startswith("-"):
        return None
    return "/" + encoded[1:].replace("-", "/")
