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


@dataclasses.dataclass
class SlackWorkspaceConfig:
    slug: str               # routing key (e.g. "sft", "codeship")
    context: str            # vault context this workspace routes to
    lookback_hours: int = DEFAULT_LOOKBACK_HOURS
    mentions_only: bool = True   # off-switch for future channel polling


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
                events.extend(self._fetch_workspace(ws))
            except SlackAuthError as e:
                log.warning("slack auth error for %s: %s", ws.slug, e)
            except Exception as e:  # noqa: BLE001
                log.warning("slack fetch failed for %s: %s", ws.slug, e)

        log.info("slack fetch: %d mention(s) across %d workspace(s)",
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


def _default_client_factory(token: str):
    """Lazy import — `slack-sdk` is heavy and only this path needs it."""
    from slack_sdk import WebClient
    return _WrappedClient(WebClient(token=token))


class _WrappedClient:
    """Thin wrapper so tests don't have to fake the slack-sdk surface area.

    The connector only needs ``auth_test`` and ``search_messages`` —
    both return plain dicts here so test doubles can return dicts too.
    """

    def __init__(self, web_client) -> None:
        self._w = web_client

    def auth_test(self) -> dict:
        return self._w.auth_test().data  # type: ignore[no-any-return]

    def search_messages(self, **kwargs) -> dict:
        return self._w.search_messages(**kwargs).data  # type: ignore[no-any-return]


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
        yield SlackWorkspaceConfig(
            slug=str(slug),
            context=str(ctx),
            lookback_hours=int(
                cfg.get("lookback_hours") or DEFAULT_LOOKBACK_HOURS
            ),
            mentions_only=bool(cfg.get("mentions_only", True)),
        )


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
