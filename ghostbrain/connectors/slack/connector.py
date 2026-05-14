"""Slack connector. Polls one or more workspaces for messages where the
authenticated user is @-mentioned over the last lookback window.

Mentions-only by design (per SPEC §9 — only mentions, not raw channel
volume). Each mention surfaces as a single event with the message text,
permalink, channel name, and the mentioning user resolved to a display
name. The user's existing ``slack.workspaces`` block in ``routing.yaml``
maps workspace slug → context, so a mention from the SFT workspace
routes straight to ``sanlam`` without an LLM call.
"""

from __future__ import annotations

import dataclasses
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.slack.auth import SlackAuthError, load_token

log = logging.getLogger("ghostbrain.connectors.slack")

DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_MAX_RESULTS = 100
DEFAULT_INITIAL_LOOKBACK_DAYS = 7
HISTORY_PAGE_LIMIT = 200


@dataclasses.dataclass
class SlackWorkspaceConfig:
    slug: str               # routing key (e.g. "sft", "codeship")
    context: str            # vault context this workspace routes to
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    # Fetch strategy:
    #   "mentions" (default, legacy) — search.messages for @-mentions only.
    #   "full"                       — conversations.history across every
    #                                  channel the user is in, with an LLM
    #                                  triage gate for ambient chatter.
    mode: str = "mentions"
    # Full-mode only:
    initial_lookback_days: int = DEFAULT_INITIAL_LOOKBACK_DAYS
    denied_channels: tuple[str, ...] = ()     # name match (case-insensitive)
    llm_filter: bool = True                   # run LLM gate on non-always-keep msgs

    # Back-compat shim. Old yaml used ``mentions_only: true``; that's now
    # ``mode: mentions`` and the old key still works for the user who
    # hasn't migrated their routing.yaml yet.
    @property
    def mentions_only(self) -> bool:
        return self.mode == "mentions"


class SlackConnector(Connector):
    """See module docstring."""

    name = "slack"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
        *,
        client_factory=None,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.workspaces: list[SlackWorkspaceConfig] = list(
            _parse_workspaces(config),
        )
        # Test seam: callers can inject a fake (token) -> WebClient.
        self._client_factory = client_factory or _default_client_factory

    def health_check(self) -> bool:
        if not self.workspaces:
            return False
        for ws in self.workspaces:
            try:
                load_token(ws.slug)
            except SlackAuthError:
                return False
        return True

    def fetch(self, since: datetime) -> list[dict]:
        if not self.workspaces:
            log.info("no slack workspaces configured; skipping")
            return []

        events: list[dict] = []
        for ws in self.workspaces:
            try:
                if ws.mode == "full":
                    events.extend(self._fetch_workspace_full(ws))
                else:
                    events.extend(self._fetch_workspace(ws))
            except SlackAuthError as e:
                log.warning("slack auth error for %s: %s", ws.slug, e)
            except Exception as e:  # noqa: BLE001
                log.warning("slack fetch failed for %s: %s", ws.slug, e)

        log.info("slack fetch: %d event(s) across %d workspace(s)",
                 len(events), len(self.workspaces))
        return events

    def normalize(self, raw: dict) -> dict:
        # ``_fetch_workspace`` produces normalized events directly.
        return raw

    # ------------------------------------------------------------------
    # Per-workspace fetch
    # ------------------------------------------------------------------

    def _fetch_workspace(self, ws: SlackWorkspaceConfig) -> list[dict]:
        token = load_token(ws.slug)
        client = self._client_factory(token)

        # Identify ourselves so we know which user_id to search mentions for.
        ident = client.auth_test()
        my_user_id = ident.get("user_id") or ident.get("user")
        team_id = ident.get("team_id") or ident.get("team")
        team_name = ident.get("team")
        if not my_user_id:
            raise SlackAuthError(
                f"slack auth.test for {ws.slug} returned no user_id"
            )

        cutoff = datetime.now(timezone.utc) - timedelta(hours=ws.lookback_hours)
        # Slack's search query supports `after:YYYY-MM-DD` (date, not time).
        query = f"<@{my_user_id}> after:{cutoff.date().isoformat()}"
        log.debug("slack %s query=%r", ws.slug, query)

        response = client.search_messages(
            query=query,
            count=DEFAULT_MAX_RESULTS,
            sort="timestamp",
            sort_dir="desc",
        )
        matches = (response.get("messages") or {}).get("matches") or []

        events: list[dict] = []
        for match in matches:
            ev = _normalize_match(
                match,
                workspace_slug=ws.slug,
                workspace_team_id=team_id,
                workspace_name=team_name,
                my_user_id=my_user_id,
            )
            if ev is not None:
                events.append(ev)
        return events

    # ------------------------------------------------------------------
    # Full-pull path — every readable channel, LLM gate for triage
    # ------------------------------------------------------------------

    def _fetch_workspace_full(
        self,
        ws: SlackWorkspaceConfig,
        *,
        dry_run_collector: list | None = None,
    ) -> list[dict]:
        """Pull every-new-message from every channel the user is in.

        ``dry_run_collector`` — when supplied, per-message decisions are
        appended to this list (as ``MessageDecision``) for the CLI to print.
        In production it stays ``None`` and we just enqueue the kept events.
        """
        from ghostbrain.connectors.slack.cursors import load_cursors
        from ghostbrain.connectors.slack.filter import (
            FilterableMessage, score_messages, KEEP_THRESHOLD,
        )

        token = load_token(ws.slug)
        client = self._client_factory(token)

        ident = client.auth_test()
        my_user_id = ident.get("user_id") or ident.get("user")
        team_id = ident.get("team_id") or ident.get("team")
        team_name = ident.get("team")
        if not my_user_id:
            raise SlackAuthError(
                f"slack auth.test for {ws.slug} returned no user_id"
            )

        cursors = load_cursors(self.state_dir, ws.slug)
        channels = _list_channels(client)
        log.info("slack full-pull %s: %d channels", ws.slug, len(channels))

        # First-run floor: don't pull more than initial_lookback_days when
        # no cursor exists. Without this, a fresh install would replay
        # months of channel history through the LLM gate.
        initial_floor = (
            datetime.now(timezone.utc)
            - timedelta(days=ws.initial_lookback_days)
        ).timestamp()

        denied = set(ws.denied_channels)
        ambient: list[tuple[dict, dict]] = []  # (channel_dict, message_dict)
        kept_always: list[tuple[dict, dict, str]] = []  # (chan, msg, reason)

        for chan in channels:
            chan_id = chan.get("id") or ""
            chan_name = (chan.get("name") or "").lower()
            if not chan_id:
                continue
            if chan_name and chan_name in denied:
                continue

            cursor_ts = cursors.get(chan_id)
            oldest = cursor_ts or f"{initial_floor:.6f}"
            try:
                msgs = _fetch_channel_messages(client, chan_id, oldest=oldest)
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "slack full-pull: history failed for %s (%s): %s",
                    chan_id, chan_name, e,
                )
                continue
            if not msgs:
                continue

            # Slack returns newest first; sort old → new so we set cursor
            # to the last (newest) ts we processed.
            msgs.sort(key=lambda m: float(m.get("ts") or 0.0))
            newest_ts = msgs[-1].get("ts") or cursor_ts
            if newest_ts:
                cursors.set(chan_id, last_ts=newest_ts, name=chan_name or chan_id)

            for m in msgs:
                if _is_noise(m):
                    if dry_run_collector is not None:
                        dry_run_collector.append(MessageDecision(
                            channel=chan_name, msg=m, kept=False,
                            reason="noise (join/leave/bot tombstone)", score=None,
                        ))
                    continue
                reason = _always_keep_reason(m, chan, my_user_id)
                if reason is not None:
                    kept_always.append((chan, m, reason))
                else:
                    ambient.append((chan, m))

        # LLM gate over ambient. Skipped when disabled — kept_always still ships.
        ambient_scores: list[int] = []
        if ambient and ws.llm_filter:
            filterables = [
                FilterableMessage(
                    channel=(c.get("name") or c.get("id") or "?"),
                    sender=(m.get("user") or m.get("username") or "unknown"),
                    text=_extract_text(m),
                    is_bot=bool(m.get("bot_id") or m.get("subtype") == "bot_message"),
                )
                for c, m in ambient
            ]
            ambient_scores = score_messages(filterables)
        elif ambient:
            ambient_scores = [KEEP_THRESHOLD] * len(ambient)

        events: list[dict] = []
        for chan, m, reason in kept_always:
            if dry_run_collector is not None:
                dry_run_collector.append(MessageDecision(
                    channel=(chan.get("name") or chan.get("id") or "?"),
                    msg=m, kept=True, reason=reason, score=None,
                ))
            ev = _normalize_message(
                m, channel=chan,
                workspace_slug=ws.slug,
                workspace_team_id=team_id,
                workspace_name=team_name,
                my_user_id=my_user_id,
                keep_reason=reason,
            )
            if ev is not None:
                events.append(ev)
        for (chan, m), score in zip(ambient, ambient_scores):
            kept = score >= KEEP_THRESHOLD
            if dry_run_collector is not None:
                dry_run_collector.append(MessageDecision(
                    channel=(chan.get("name") or chan.get("id") or "?"),
                    msg=m, kept=kept,
                    reason=f"llm score {score}",
                    score=score,
                ))
            if not kept:
                continue
            ev = _normalize_message(
                m, channel=chan,
                workspace_slug=ws.slug,
                workspace_team_id=team_id,
                workspace_name=team_name,
                my_user_id=my_user_id,
                keep_reason=f"llm:{score}",
            )
            if ev is not None:
                events.append(ev)

        if dry_run_collector is None:
            cursors.save()
        log.info(
            "slack full-pull %s: %d kept (%d always, %d via LLM ≥ %d) "
            "out of %d ambient considered",
            ws.slug, len(events), len(kept_always),
            sum(1 for s in ambient_scores if s >= KEEP_THRESHOLD),
            KEEP_THRESHOLD, len(ambient),
        )
        return events


@dataclasses.dataclass
class MessageDecision:
    """Dry-run output: one row per message considered."""
    channel: str
    msg: dict
    kept: bool
    reason: str
    score: int | None


# ---------------------------------------------------------------------------
# Slack API helpers (pure given a client)
# ---------------------------------------------------------------------------


def _list_channels(client) -> list[dict]:
    """Page through users_conversations and return all channel descriptors."""
    out: list[dict] = []
    cursor = None
    while True:
        kw = {
            "types": "public_channel,private_channel,mpim,im",
            "exclude_archived": True,
            "limit": 1000,
        }
        if cursor:
            kw["cursor"] = cursor
        page = client.users_conversations(**kw)
        out.extend(page.get("channels") or [])
        cursor = (page.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return out


def _fetch_channel_messages(client, channel_id: str, *, oldest: str) -> list[dict]:
    """Page through conversations_history for a single channel. ``oldest``
    is the Slack ``ts`` floor — Slack treats it as a strict lower bound
    (messages with ts == oldest are NOT returned), which is exactly what
    we want when ``oldest`` is the last cursor we saved.

    Slack tier-3 limits conversations.history to ~50 calls/minute. With
    hundreds of channels we burst past that. We catch the
    ``ratelimited`` error, honor the ``Retry-After`` header when
    present, then retry once. A second rate-limit gives up on this
    channel — next run picks up where we left off.
    """
    out: list[dict] = []
    cursor = None
    while True:
        kw = {"channel": channel_id, "oldest": oldest, "limit": HISTORY_PAGE_LIMIT}
        if cursor:
            kw["cursor"] = cursor
        page = _call_with_backoff(
            lambda: client.conversations_history(**kw),
        )
        if page is None:
            break  # gave up; cursor not advanced, next run retries
        out.extend(page.get("messages") or [])
        if not page.get("has_more"):
            break
        cursor = (page.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
    return out


def _call_with_backoff(call):
    """Run a Slack API call, honoring one ``ratelimited`` retry.

    Imported errors lazily so the connector module doesn't pay the
    slack-sdk import cost unless we're actually using it.
    """
    import time
    try:
        from slack_sdk.errors import SlackApiError
    except ImportError:
        # Tests inject fakes that won't raise SlackApiError; just call.
        return call()

    try:
        return call()
    except SlackApiError as e:
        if (e.response.data or {}).get("error") != "ratelimited":
            raise
        # Slack sends Retry-After (seconds) in the response headers.
        retry_after = int(e.response.headers.get("Retry-After", "30") or 30)
        retry_after = min(retry_after, 60)  # cap so a 5-min wait doesn't stall the whole pull
        log.info("slack ratelimited; sleeping %ds before retry", retry_after)
        time.sleep(retry_after)
        try:
            return call()
        except SlackApiError as e2:
            log.warning("slack still ratelimited after retry; giving up on this call")
            return None


def _is_noise(m: dict) -> bool:
    """System events we never want to surface, plus messages with no
    judgable content. A message with empty effective text is either a
    pure-blocks layout we can't extract OR a tombstone — either way the
    LLM can't triage it and shouldn't be charged the round-trip."""
    subtype = m.get("subtype") or ""
    if subtype in {
        "channel_join", "channel_leave", "channel_archive",
        "channel_unarchive", "channel_topic", "channel_purpose",
        "channel_name", "pinned_item", "unpinned_item",
        "reminder_add", "reminder_delete",
    }:
        return True
    return not _extract_text(m).strip()


def _extract_text(m: dict) -> str:
    """Return the most informative text we can pull from a Slack message.

    Slack puts content in three places: top-level ``text``, each
    ``attachments[*].text`` (and ``pretext``/``fallback``), and
    ``blocks[*]`` (rich layout). Bots like DLQ alerts use only
    attachments — sending their empty ``text`` to the LLM is what made
    the dry-run gate degenerate to "keep everything".

    We concatenate (text, attachment text/pretext/fallback) in order.
    Block extraction is best-effort: only ``section`` blocks expose
    text in a stable shape; we ignore the rest. Empty string when
    nothing extractable.
    """
    parts: list[str] = []
    top = (m.get("text") or "").strip()
    if top:
        parts.append(top)

    for att in m.get("attachments") or []:
        for key in ("pretext", "title", "text", "fallback"):
            v = (att.get(key) or "").strip()
            if v:
                parts.append(v)
                break  # one piece per attachment is enough for triage

    for block in m.get("blocks") or []:
        if block.get("type") == "section":
            text_obj = block.get("text") or {}
            v = (text_obj.get("text") or "").strip()
            if v:
                parts.append(v)

    return "\n".join(parts)


def _always_keep_reason(m: dict, channel: dict, my_user_id: str) -> str | None:
    """Decide if a message bypasses the LLM gate.

    Returns the reason string (used for dry-run display + event metadata),
    or None when the message should go through the LLM gate.
    """
    text = m.get("text") or ""
    mention_token = f"<@{my_user_id}>"
    if mention_token in text:
        return "mention"
    if m.get("user") == my_user_id:
        return "my_message"
    if channel.get("is_im"):
        return "dm"
    return None


def _default_client_factory(token: str):
    """Lazy import — `slack-sdk` is heavy and only this path needs it."""
    from slack_sdk import WebClient
    return _WrappedClient(WebClient(token=token))


class _WrappedClient:
    """Thin wrapper so tests don't have to fake the slack-sdk surface area.

    The connector needs ``auth_test`` + ``search_messages`` (mentions
    mode) and ``users_conversations`` + ``conversations_history``
    (full-pull mode). All return plain dicts so test doubles can return
    dicts too.
    """

    def __init__(self, web_client) -> None:
        self._w = web_client

    def auth_test(self) -> dict:
        return self._w.auth_test().data  # type: ignore[no-any-return]

    def search_messages(self, **kwargs) -> dict:
        return self._w.search_messages(**kwargs).data  # type: ignore[no-any-return]

    def users_conversations(self, **kwargs) -> dict:
        return self._w.users_conversations(**kwargs).data  # type: ignore[no-any-return]

    def conversations_history(self, **kwargs) -> dict:
        return self._w.conversations_history(**kwargs).data  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _parse_workspaces(config: dict) -> Iterable[SlackWorkspaceConfig]:
    """``config['workspaces']`` shape::

        workspaces:
          sft:
            context: sanlam
            lookback_hours: 24
            mentions_only: true
          codeship:
            context: codeship

    Empty config → empty iterator.
    """
    raw = (config or {}).get("workspaces") or {}
    for slug, cfg in raw.items():
        cfg = cfg or {}
        ctx = cfg.get("context")
        if not ctx:
            log.warning("slack workspace %s has no context; skipping", slug)
            continue
        # mode resolution:
        #   explicit `mode: full|mentions` wins
        #   else legacy `mentions_only: false` → full
        #   else default → mentions
        if "mode" in cfg:
            mode = str(cfg.get("mode") or "mentions").lower()
        elif cfg.get("mentions_only") is False:
            mode = "full"
        else:
            mode = "mentions"
        if mode not in ("mentions", "full"):
            log.warning(
                "slack workspace %s has unknown mode %r; defaulting to mentions",
                slug, mode,
            )
            mode = "mentions"

        denied_raw = cfg.get("denied_channels") or ()
        denied = tuple(str(d).lower() for d in denied_raw if d)

        yield SlackWorkspaceConfig(
            slug=str(slug),
            context=str(ctx),
            lookback_hours=int(
                cfg.get("lookback_hours") or DEFAULT_LOOKBACK_HOURS
            ),
            mode=mode,
            initial_lookback_days=int(
                cfg.get("initial_lookback_days")
                or DEFAULT_INITIAL_LOOKBACK_DAYS
            ),
            denied_channels=denied,
            llm_filter=bool(cfg.get("llm_filter", True)),
        )


def _normalize_message(
    m: dict,
    *,
    channel: dict,
    workspace_slug: str,
    workspace_team_id: str | None,
    workspace_name: str | None,
    my_user_id: str,
    keep_reason: str,
) -> dict | None:
    """Convert a conversations.history message to the standard event shape.

    Different from ``_normalize_match`` (which handles search.messages
    payloads): conversations.history returns the channel descriptor
    separately, no embedded permalink, and only the raw ``user`` id.
    """
    text = _extract_text(m)
    ts = m.get("ts") or ""
    if not ts:
        return None

    channel_id = channel.get("id") or ""
    channel_name = channel.get("name") or ""
    is_dm = bool(channel.get("is_im"))
    is_mpim = bool(channel.get("is_mpim"))

    user_id = m.get("user") or ""
    bot_id = m.get("bot_id") or ""
    sender_id = user_id or (f"bot:{bot_id}" if bot_id else "")
    user_name = m.get("username") or ""

    title = _build_title(
        channel_name=channel_name, is_dm=is_dm, is_mpim=is_mpim,
        user_name=user_name or sender_id or "unknown", text=text,
    )

    event_id = (
        f"slack:msg:{workspace_team_id or workspace_slug}:"
        f"{channel_id or 'unknown'}:{ts}"
    )

    return {
        "id": event_id,
        "source": "slack",
        "type": "slack_message",
        "subtype": keep_reason,
        "timestamp": _slack_ts_to_iso(ts),
        "actorId": f"slack:{sender_id}" if sender_id else "slack:unknown",
        "title": title,
        "body": text,
        "sourceUrl": "",  # populated lazily by the worker via chat.getPermalink
        "metadata": {
            "workspace_slug": workspace_slug,
            "workspace_id": workspace_team_id,
            "workspace_name": workspace_name,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "is_dm": is_dm,
            "is_mpim": is_mpim,
            "user_id": user_id,
            "user_name": user_name,
            "bot_id": bot_id,
            "thread_ts": m.get("thread_ts") or ts,
            "my_user_id": my_user_id,
            "keep_reason": keep_reason,
        },
    }


def _normalize_match(
    match: dict,
    *,
    workspace_slug: str,
    workspace_team_id: str | None,
    workspace_name: str | None,
    my_user_id: str,
) -> dict | None:
    """Convert a search.messages match payload to the standard event shape."""
    text = (match.get("text") or "").strip()
    ts = match.get("ts") or ""
    if not ts:
        return None

    channel = match.get("channel") or {}
    channel_id = channel.get("id") or ""
    channel_name = channel.get("name") or ""
    is_dm = bool(channel.get("is_im"))
    is_mpim = bool(channel.get("is_mpim"))

    user_id = match.get("user") or ""
    user_name = match.get("username") or ""

    permalink = match.get("permalink") or ""
    iter_url = (match.get("iid") or "")  # internal id; not user-facing

    title = _build_title(
        channel_name=channel_name, is_dm=is_dm, is_mpim=is_mpim,
        user_name=user_name or user_id, text=text,
    )

    event_id = (
        f"slack:msg:{workspace_team_id or workspace_slug}:"
        f"{channel_id or 'unknown'}:{ts}"
    )

    return {
        "id": event_id,
        "source": "slack",
        "type": "slack_message",
        "subtype": "mention",
        "timestamp": _slack_ts_to_iso(ts),
        "actorId": f"slack:{user_id}" if user_id else "slack:unknown",
        "title": title,
        "body": text,
        "sourceUrl": permalink or iter_url,
        "metadata": {
            "workspace_slug": workspace_slug,
            "workspace_id": workspace_team_id,
            "workspace_name": workspace_name,
            "channel_id": channel_id,
            "channel_name": channel_name,
            "is_dm": is_dm,
            "is_mpim": is_mpim,
            "user_id": user_id,
            "user_name": user_name,
            "thread_ts": match.get("thread_ts") or ts,
            "permalink": permalink,
            "my_user_id": my_user_id,
        },
    }


def _build_title(
    *,
    channel_name: str,
    is_dm: bool,
    is_mpim: bool,
    user_name: str,
    text: str,
) -> str:
    if is_dm:
        location = f"DM with {user_name}" if user_name else "DM"
    elif is_mpim:
        location = "group DM"
    elif channel_name:
        location = f"#{channel_name}"
    else:
        location = "Slack"
    snippet = text[:80].replace("\n", " ").strip()
    if len(text) > 80:
        snippet += "…"
    return f"{location}: {snippet}" if snippet else location


def _slack_ts_to_iso(ts: str) -> str:
    """Slack ts is ``"1715000000.001234"`` (epoch seconds, microseconds suffix)."""
    try:
        seconds = float(ts)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
