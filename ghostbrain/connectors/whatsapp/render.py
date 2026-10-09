"""Render one chat-day of WhatsApp messages as a markdown transcript.

Type codes were settled against the real store on 2026-10-09 (see spec);
anything not listed here is dropped.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ghostbrain.connectors.whatsapp.store import Message

VoiceLine = Callable[[Message], tuple[str, bool]]

TEXT, IMAGE, VIDEO, VOICE, CONTACT, LOCATION, LINK, DOCUMENT, GIF = 0, 1, 2, 3, 4, 5, 7, 8, 11


@dataclass
class RenderedDay:
    body: str = ""
    lines: int = 0
    voice_notes: int = 0
    pending: bool = False
    participants: list[str] = field(default_factory=list)


def _labelled(label: str, detail: str | None) -> str:
    detail = (detail or "").strip()
    return f"[{label}: {detail}]" if detail else f"[{label}]"


def _content(m: Message) -> str | None:
    t = m.type_code
    if t in (TEXT, LINK):
        return (m.text or "").strip() or None
    if t == IMAGE:
        return _labelled("image", m.caption)
    if t == VIDEO:
        return _labelled("video", m.caption)
    if t == CONTACT:
        return "[contact card]"
    if t == LOCATION:
        return "[location]"
    if t == DOCUMENT:
        return _labelled("document", m.text)
    if t == GIF:
        return "[gif]"
    return None


def render_day(messages: list[Message], voice: VoiceLine) -> RenderedDay:
    out = RenderedDay()
    blocks: list[str] = []
    senders: set[str] = set()
    for m in messages:
        if m.type_code == VOICE:
            content, pending = voice(m)
            out.voice_notes += 1
            out.pending = out.pending or pending
        else:
            content = _content(m)
        if not content:
            continue
        head, *rest = content.split("\n")
        blocks.append("\n".join([f"**{m.at:%H:%M} {m.sender}:** {head}",
                                 *(f"  {r}" for r in rest)]))
        senders.add(m.sender)
    out.body = "\n".join(blocks)
    out.lines = len(blocks)
    out.participants = sorted(senders)
    return out
