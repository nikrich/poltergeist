"""Teams chat connector. Lists /me/chats, pulls messages created since
last_run from active chats (capped, system messages dropped), applies the
shared LLM relevance gate, and emits one event per message."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors._relevance import apply_relevance_gate, build_llm_gate
from ghostbrain.connectors.microsoft.graph.auth import get_token, have_token
from ghostbrain.connectors.microsoft.graph.client import GraphClient

log = logging.getLogger("ghostbrain.connectors.teams_chat")

DEFAULT_MAX_PER_RUN = 100
DEFAULT_RELEVANCE_MODEL = "haiku"
_SYSTEM_TYPES = {"systemEventMessage"}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class TeamsChatConnector(Connector):
    name = "teams_chat"
    version = "1.0"

    def __init__(self, config, queue_dir, state_dir, *, client=None, relevance_gate=None):
        super().__init__(config, queue_dir, state_dir)
        self.max_per_run = int(config.get("max_messages_per_run") or DEFAULT_MAX_PER_RUN)
        self.relevance_enabled = bool(config.get("relevance_gate", True))
        self.relevance_model = str(config.get("relevance_model") or DEFAULT_RELEVANCE_MODEL)
        self._client = client
        self._gate_override = relevance_gate

    def health_check(self) -> bool:
        return have_token(self.config)

    def _graph(self) -> GraphClient:
        return self._client if self._client is not None else GraphClient(get_token(self.config))

    def fetch(self, since: datetime) -> list[dict]:
        client = self._graph()
        chats = client.get_all("/me/chats", {"$top": 50}, max_items=50)
        events: list[dict] = []
        for chat in chats:
            if len(events) >= self.max_per_run:
                break
            last = _parse_dt(chat.get("lastUpdatedDateTime"))
            if last is not None and last <= since:
                continue
            try:
                events.extend(self._messages_for(client, chat, since))
            except Exception as e:  # noqa: BLE001
                log.warning("teams_chat: chat %s failed: %s", chat.get("id"), e)

        raw = len(events)
        if self.relevance_enabled and events:
            gate = self._gate_override or self._default_gate()
            events, dropped = apply_relevance_gate(events, gate)
        else:
            dropped = 0
        log.info("teams_chat fetch: %d kept (%d gated, %d initial)", len(events), dropped, raw)
        return events

    def normalize(self, raw: dict) -> dict:
        return raw

    def _messages_for(self, client, chat: dict, since: datetime) -> list[dict]:
        cid = chat["id"]
        msgs = client.get_all(f"/me/chats/{cid}/messages", {"$top": 50}, max_items=self.max_per_run)
        out = []
        for m in msgs:
            if m.get("messageType") in _SYSTEM_TYPES:
                continue
            created = _parse_dt(m.get("createdDateTime"))
            if created is None or created <= since:
                continue
            ev = _normalize_message(chat, m)
            if ev["body"]:
                out.append(ev)
        return out

    def _default_gate(self):
        from ghostbrain.paths import vault_path

        return build_llm_gate(
            prompt_path=vault_path() / "90-meta" / "prompts" / "teams-chat-relevance.md",
            model=self.relevance_model,
            excerpt_fn=_chat_excerpt,
        )


def _parse_dt(value):
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _normalize_message(chat: dict, msg: dict) -> dict:
    cid = chat.get("id") or ""
    mid = msg.get("id") or ""
    sender = ((msg.get("from") or {}).get("user") or {})
    body_obj = msg.get("body") or {}
    content = body_obj.get("content") or ""
    if (body_obj.get("contentType") or "").lower() == "html":
        content = _HTML_TAG_RE.sub("", content).strip()
    topic = chat.get("topic") or sender.get("displayName") or "chat"
    return {
        "id": f"microsoft:chat:{cid}:{mid}",
        "source": "teams_chat",
        "type": "chat_message",
        "timestamp": msg.get("createdDateTime") or "",
        "actorId": f"microsoft:{sender.get('id')}" if sender.get("id") else "",
        "title": topic,
        "body": content,
        "sourceUrl": chat.get("webUrl") or "",
        "metadata": {
            "chatId": cid,
            "chatType": chat.get("chatType") or "",
            "sender": sender.get("displayName") or "",
        },
    }


def _chat_excerpt(event: dict) -> str:
    md = event.get("metadata") or {}
    return "\n".join([
        f"Chat: {event.get('title') or ''} ({md.get('chatType') or ''})",
        f"From: {md.get('sender') or ''}",
        "",
        (event.get("body") or "")[:1000],
    ])
