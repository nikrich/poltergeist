"""Outlook mail connector. Polls /me/messages for unread mail within a
lookback window (and/or monitored folders), applies a denylist + the shared
LLM relevance gate, and emits one event per message."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors._relevance import apply_relevance_gate, build_llm_gate
from ghostbrain.connectors.microsoft.graph.auth import get_token, have_token
from ghostbrain.connectors.microsoft.graph.client import GraphClient

log = logging.getLogger("ghostbrain.connectors.outlook_mail")

DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_MAX_PER_RUN = 50
DEFAULT_BODY_CAP_CHARS = 4000
DEFAULT_RELEVANCE_MODEL = "haiku"


class OutlookMailConnector(Connector):
    name = "outlook_mail"
    version = "1.0"

    def __init__(self, config, queue_dir, state_dir, *, client=None, relevance_gate=None):
        super().__init__(config, queue_dir, state_dir)
        self.lookback_hours = int(config.get("unread_lookback_hours") or DEFAULT_LOOKBACK_HOURS)
        self.max_per_run = int(config.get("max_messages_per_run") or DEFAULT_MAX_PER_RUN)
        self.denylist = [d.lower() for d in (config.get("denylist_domains") or [])]
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
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        params = {
            "$filter": f"isRead eq false and receivedDateTime ge {cutoff.isoformat()}",
            "$select": "id,subject,isRead,receivedDateTime,bodyPreview,from,toRecipients,webLink",
            "$top": self.max_per_run,
            "$orderby": "receivedDateTime desc",
        }
        msgs = client.get_all("/me/messages", params, max_items=self.max_per_run)
        events = [_normalize_message(m, DEFAULT_BODY_CAP_CHARS) for m in msgs]

        raw = len(events)
        events = [e for e in events if not _is_denied(e, self.denylist)]
        denied = raw - len(events)

        if self.relevance_enabled:
            gate = self._gate_override or self._default_gate()
            events, dropped = apply_relevance_gate(events, gate)
        else:
            dropped = 0
        log.info("outlook_mail fetch: %d kept (%d denied, %d gated, %d initial)",
                 len(events), denied, dropped, raw)
        return events

    def normalize(self, raw: dict) -> dict:
        return raw

    def _default_gate(self):
        from ghostbrain.paths import vault_path

        return build_llm_gate(
            prompt_path=vault_path() / "90-meta" / "prompts" / "outlook-mail-relevance.md",
            model=self.relevance_model,
            excerpt_fn=_mail_excerpt,
        )


def _normalize_message(m: dict, body_cap: int) -> dict:
    addr_obj = (m.get("from") or {}).get("emailAddress") or {}
    from_addr = (addr_obj.get("address") or "").lower()
    from_domain = from_addr.split("@", 1)[1] if "@" in from_addr else ""
    to_addrs = [
        (r.get("emailAddress") or {}).get("address", "")
        for r in (m.get("toRecipients") or [])
    ]
    return {
        "id": f"microsoft:mail:{m.get('id') or ''}",
        "source": "outlook_mail",
        "type": "email",
        "subtype": "read" if m.get("isRead") else "unread",
        "timestamp": m.get("receivedDateTime") or "",
        "actorId": f"microsoft:{from_addr}" if from_addr else "",
        "title": m.get("subject") or "(no subject)",
        "body": (m.get("bodyPreview") or "")[:body_cap],
        "sourceUrl": m.get("webLink") or "",
        "metadata": {
            "from": addr_obj.get("name") or from_addr,
            "from_address": from_addr,
            "from_domain": from_domain,
            "to": to_addrs,
            "is_unread": not m.get("isRead"),
        },
    }


def _is_denied(event: dict, denylist: list[str]) -> bool:
    if not denylist:
        return False
    domain = ((event.get("metadata") or {}).get("from_domain") or "").lower()
    if not domain:
        return False
    for pat in denylist:
        pat = pat.strip().lower()
        if not pat:
            continue
        if pat.startswith("*."):
            tail = pat[2:]
            if domain == tail or domain.endswith("." + tail):
                return True
        elif domain == pat:
            return True
    return False


def _mail_excerpt(event: dict) -> str:
    md = event.get("metadata") or {}
    return "\n".join([
        f"From: {md.get('from_address') or ''}",
        f"Subject: {event.get('title') or ''}",
        "",
        (event.get("body") or "")[:1000],
    ])
