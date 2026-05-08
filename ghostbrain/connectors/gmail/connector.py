"""Gmail connector. Polls one or more Google accounts via the Gmail API,
yielding one event per recently-touched thread.

The fetch query is intentionally narrow:
- threads with any of the configured monitored labels (label prefix +
  exact label match), OR
- unread threads from the last ``unread_lookback_hours``

This keeps the noise floor low — we don't want every newsletter and CI
notification to land in the inbox. Routing decisions then run against
the email's headers + labels.
"""

from __future__ import annotations

import base64
import dataclasses
import email.utils
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.gmail.auth import GmailAuthError, load_credentials

log = logging.getLogger("ghostbrain.connectors.gmail")

DEFAULT_UNREAD_LOOKBACK_HOURS = 24
DEFAULT_MAX_THREADS_PER_RUN = 50
DEFAULT_BODY_CAP_CHARS = 4000
DEFAULT_RELEVANCE_MODEL = "haiku"

GMAIL_RELEVANCE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relevant", "reason"],
    "properties": {
        "relevant": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 200},
    },
}


@dataclasses.dataclass
class GmailAccountConfig:
    """One Gmail account to poll. Mirrors the shape we expect in
    ``routing.yaml:gmail.accounts`` plus any per-account overrides."""

    email: str
    monitored_labels: list[str] = dataclasses.field(default_factory=list)
    unread_lookback_hours: int = DEFAULT_UNREAD_LOOKBACK_HOURS


class GmailConnector(Connector):
    """See module docstring."""

    name = "gmail"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
        *,
        service=None,
        relevance_gate=None,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.accounts: list[GmailAccountConfig] = list(_parse_accounts(config))
        self.denylist: list[str] = [
            d.lower() for d in (config.get("denylist_domains") or [])
        ]
        self.relevance_enabled = bool(config.get("relevance_gate", True))
        self.relevance_model = str(
            config.get("relevance_model") or DEFAULT_RELEVANCE_MODEL
        )
        self._service_override = service  # for tests
        # ``relevance_gate`` test override returns (relevant: bool, reason: str)
        self._relevance_override = relevance_gate

    def health_check(self) -> bool:
        if not self.accounts:
            return False
        for acc in self.accounts:
            try:
                load_credentials(acc.email)
            except GmailAuthError:
                return False
        return True

    def fetch(self, since: datetime) -> list[dict]:
        if not self.accounts:
            log.info("no monitored gmail accounts configured; skipping")
            return []

        events: list[dict] = []
        for acc in self.accounts:
            try:
                events.extend(self._fetch_account(acc))
            except GmailAuthError as e:
                log.warning("gmail auth error for %s: %s", acc.email, e)
            except Exception as e:  # noqa: BLE001
                log.warning("gmail fetch failed for %s: %s", acc.email, e)

        raw_count = len(events)
        events = [e for e in events if not _is_denied(e, self.denylist)]
        denied = raw_count - len(events)

        if self.relevance_enabled:
            events, dropped_by_llm = self._apply_relevance_gate(events)
        else:
            dropped_by_llm = 0

        log.info(
            "gmail fetch: %d kept (%d denylisted, %d dropped by LLM gate, "
            "%d initial)",
            len(events), denied, dropped_by_llm, raw_count,
        )
        return events

    def _apply_relevance_gate(
        self, events: list[dict],
    ) -> tuple[list[dict], int]:
        """Run an LLM relevance check per thread; drop the irrelevant ones.

        Returns ``(kept, dropped_count)``. Failures are conservative:
        when the LLM call errors, we keep the event so noise removal
        never silently swallows real signal.
        """
        if not events:
            return events, 0

        gate = self._relevance_override or _default_relevance_gate(
            self.relevance_model,
        )
        kept: list[dict] = []
        dropped = 0
        for ev in events:
            try:
                relevant, reason = gate(ev)
            except Exception as e:  # noqa: BLE001
                log.warning("gmail relevance gate errored for %s: %s — keeping",
                            ev.get("id"), e)
                kept.append(ev)
                continue
            if relevant:
                ev.setdefault("metadata", {})["relevanceReason"] = reason
                kept.append(ev)
            else:
                dropped += 1
                log.info("gmail dropped by relevance gate id=%s reason=%s",
                         ev.get("id"), reason)
        return kept, dropped

    def normalize(self, raw: dict) -> dict:
        # `_fetch_account` produces normalized events directly.
        return raw

    # ------------------------------------------------------------------
    # Fetching one account
    # ------------------------------------------------------------------

    def _fetch_account(self, acc: GmailAccountConfig) -> list[dict]:
        service = self._service_override or self._build_service(acc.email)
        query = _build_query(acc)
        log.debug("gmail %s query=%r", acc.email, query)

        response = service.users().threads().list(
            userId="me", q=query, maxResults=DEFAULT_MAX_THREADS_PER_RUN,
        ).execute()
        threads = response.get("threads") or []

        events: list[dict] = []
        for stub in threads:
            tid = stub.get("id")
            if not tid:
                continue
            full = service.users().threads().get(
                userId="me", id=tid, format="full",
            ).execute()
            event = _normalize_thread(full, account=acc.email)
            if event is not None:
                events.append(event)
        return events

    def _build_service(self, account_email: str):
        # Lazy import — heavy.
        from googleapiclient.discovery import build
        creds = load_credentials(account_email)
        return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------------
# Pure helpers (heavily tested with mocks)
# ---------------------------------------------------------------------------


def _is_denied(event: dict, denylist: list[str]) -> bool:
    """Match an event's sender domain against the denylist.

    Patterns:
    - ``humblebundle.com`` — exact domain match
    - ``*.humblebundle.com`` — match any subdomain
    - ``mailer.humblebundle.com`` — exact subdomain match

    The match is case-insensitive and tested against the normalized
    ``metadata.from_domain`` we extracted at parse time.
    """
    if not denylist:
        return False
    domain = ((event.get("metadata") or {}).get("from_domain") or "").lower()
    if not domain:
        return False
    for pattern in denylist:
        pat = pattern.strip().lower()
        if not pat:
            continue
        if pat.startswith("*."):
            tail = pat[2:]
            if domain == tail or domain.endswith("." + tail):
                return True
        else:
            if domain == pat:
                return True
    return False


def _default_relevance_gate(model: str):
    """Build the default LLM-backed relevance check.

    The closure captures the prompt template and the model name. It
    returns ``(relevant: bool, reason: str)`` per event and is
    swappable for a fake in tests.
    """
    from ghostbrain.llm import client as llm
    from ghostbrain.paths import vault_path

    prompt_path = vault_path() / "90-meta" / "prompts" / "gmail-relevance.md"
    if not prompt_path.exists():
        raise FileNotFoundError(
            "missing prompt gmail-relevance.md; re-run `ghostbrain-bootstrap`"
        )
    template = prompt_path.read_text(encoding="utf-8")

    def gate(event: dict) -> tuple[bool, str]:
        excerpt = _build_relevance_excerpt(event)
        prompt = template.replace("{{content}}", excerpt)
        result = llm.run(
            prompt,
            model=model,
            json_schema=GMAIL_RELEVANCE_SCHEMA,
            budget_usd=0.05,
        )
        payload = result.as_json()
        return bool(payload.get("relevant")), str(payload.get("reason") or "")

    return gate


def _build_relevance_excerpt(event: dict) -> str:
    md = event.get("metadata") or {}
    parts = [
        f"From: {md.get('from') or md.get('from_address') or ''}",
        f"Subject: {event.get('title') or ''}",
        f"Labels: {', '.join(md.get('labels') or [])}",
        f"Snippet: {md.get('snippet') or ''}",
    ]
    body = (event.get("body") or "")[:1000]
    if body:
        parts.append("")
        parts.append(body)
    return "\n".join(parts)


def _parse_accounts(config: dict) -> Iterable[GmailAccountConfig]:
    """``config`` shape::

        accounts:
          jannik811@gmail.com:
            monitored_labels: ["sanlam/policies", "codeship"]
            unread_lookback_hours: 24
          # ...

    Empty config → empty iterator.
    """
    accounts = (config or {}).get("accounts") or {}
    for email_addr, cfg in accounts.items():
        cfg = cfg or {}
        yield GmailAccountConfig(
            email=str(email_addr),
            monitored_labels=list(cfg.get("monitored_labels") or []),
            unread_lookback_hours=int(
                cfg.get("unread_lookback_hours") or DEFAULT_UNREAD_LOOKBACK_HOURS
            ),
        )


def _build_query(acc: GmailAccountConfig) -> str:
    """Compose the Gmail search query that selects threads to ingest.

    We OR together two filters so a thread surfaces if EITHER it has a
    monitored label OR it's unread within the lookback window. Without
    monitored labels configured, we fall back to the unread-only filter.
    """
    parts: list[str] = []
    if acc.monitored_labels:
        labels = " OR ".join(
            f"label:{_quote_label(label)}" for label in acc.monitored_labels
        )
        parts.append(f"({labels})")

    hours = max(1, acc.unread_lookback_hours)
    if hours <= 24:
        unread_filter = "is:unread newer_than:1d"
    else:
        days = max(1, hours // 24)
        unread_filter = f"is:unread newer_than:{days}d"
    parts.append(unread_filter)

    return " OR ".join(parts) if len(parts) > 1 else parts[0]


def _quote_label(label: str) -> str:
    """Gmail labels with spaces or punctuation must be quoted in queries."""
    if re.fullmatch(r"[A-Za-z0-9_/\-]+", label):
        return label
    escaped = label.replace('"', '\\"')
    return f'"{escaped}"'


def _normalize_thread(thread: dict, *, account: str) -> dict | None:
    """Convert a Gmail thread payload to ghostbrain's standard event shape."""
    messages = thread.get("messages") or []
    if not messages:
        return None
    latest = messages[-1]
    headers = _headers_dict(latest.get("payload", {}).get("headers", []))

    thread_id = thread.get("id") or latest.get("threadId") or ""
    if not thread_id:
        return None

    subject = headers.get("subject") or "(no subject)"
    from_header = headers.get("from") or ""
    from_name, from_addr = email.utils.parseaddr(from_header)
    from_domain = from_addr.split("@", 1)[1].lower() if "@" in from_addr else ""

    to_header = headers.get("to") or ""
    to_addrs = [
        addr for _, addr in email.utils.getaddresses([to_header]) if addr
    ]

    labels = list(_collect_thread_labels(messages))
    is_unread = "UNREAD" in labels
    snippet = (latest.get("snippet") or thread.get("snippet") or "").strip()

    body = _extract_text_body(latest.get("payload", {}))[:DEFAULT_BODY_CAP_CHARS]
    timestamp = _internal_date_to_iso(latest.get("internalDate"))

    url = f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"

    return {
        "id": f"gmail:thread:{thread_id}",
        "source": "gmail",
        "type": "email_thread",
        "subtype": "unread" if is_unread else "read",
        "timestamp": timestamp,
        "actorId": f"gmail:{from_addr}" if from_addr else f"gmail:{account}",
        "title": subject,
        "body": body or snippet,
        "sourceUrl": url,
        "metadata": {
            "thread_id": thread_id,
            "account": account,
            "msg_count": len(messages),
            "labels": labels,
            "from": from_header,
            "from_name": from_name,
            "from_address": from_addr,
            "from_domain": from_domain,
            "to": to_addrs,
            "snippet": snippet,
            "is_unread": is_unread,
        },
    }


def _headers_dict(headers: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for h in headers or []:
        name = (h.get("name") or "").lower()
        if name and name not in out:
            out[name] = h.get("value") or ""
    return out


def _collect_thread_labels(messages: list[dict]) -> Iterable[str]:
    seen: set[str] = set()
    for m in messages:
        for label in m.get("labelIds") or []:
            if label not in seen:
                seen.add(label)
                yield label


def _extract_text_body(payload: dict) -> str:
    """Walk the MIME tree and prefer ``text/plain`` over ``text/html``.

    Gmail returns nested ``parts`` for multipart messages. Single-part
    messages put the body directly on the payload.
    """
    if not payload:
        return ""
    mime = (payload.get("mimeType") or "").lower()
    body = payload.get("body") or {}

    if mime == "text/plain" and body.get("data"):
        return _decode_b64url(body["data"])

    plain_buffer: list[str] = []
    html_buffer: list[str] = []
    for part in payload.get("parts") or []:
        text = _extract_text_body(part)
        if not text:
            continue
        sub_mime = (part.get("mimeType") or "").lower()
        if sub_mime == "text/plain":
            plain_buffer.append(text)
        elif sub_mime == "text/html":
            html_buffer.append(text)
        else:
            plain_buffer.append(text)

    if plain_buffer:
        return "\n\n".join(plain_buffer)
    if html_buffer:
        return _strip_html("\n\n".join(html_buffer))
    if mime == "text/html" and body.get("data"):
        return _strip_html(_decode_b64url(body["data"]))
    return ""


def _decode_b64url(data: str) -> str:
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        return ""


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_WS_RE = re.compile(r"\n\s*\n\s*\n+")


def _strip_html(html: str) -> str:
    text = _HTML_TAG_RE.sub("", html)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return _HTML_WS_RE.sub("\n\n", text).strip()


def _internal_date_to_iso(internal_date: str | int | None) -> str:
    """Gmail's ``internalDate`` is ms-since-epoch as a string."""
    if internal_date is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        ms = int(internal_date)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()
