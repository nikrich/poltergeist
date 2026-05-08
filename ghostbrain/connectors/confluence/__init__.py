"""Confluence Cloud connector. Fetches pages updated in monitored spaces
within the last day."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.atlassian._base import (
    AtlassianAuthError,
    AtlassianClient,
    auth_for_site,
    slug_for_host,
)

log = logging.getLogger("ghostbrain.connectors.confluence")

FIRST_RUN_LOOKBACK_HOURS = 24
WINDOW_OVERLAP_HOURS = 2
MAX_RESULTS = 25


class ConfluenceConnector(Connector):
    name = "confluence"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        # config["spaces"] is a dict of {space_key: context}.
        self.space_map: dict[str, str] = dict(config.get("spaces") or {})
        # config["sites"] is a list of hosts. Each site uses its own auth.
        self.sites: list[str] = list(config.get("sites") or [])
        self.lookback_hours = int(config.get("lookback_hours") or 24)

    def health_check(self) -> bool:
        if not self.sites:
            return False
        try:
            for host in self.sites:
                email, token = auth_for_site(host)
                client = AtlassianClient(host, email, token)
                client.get("/wiki/rest/api/user/current")
        except (AtlassianAuthError, Exception) as e:
            log.warning("confluence health check failed: %s", e)
            return False
        return True

    def fetch(self, since: datetime) -> list[dict]:
        if not self.sites or not self.space_map:
            log.info("no confluence sites/spaces configured; skipping fetch")
            return []

        floor = datetime.now(timezone.utc) - timedelta(hours=FIRST_RUN_LOOKBACK_HOURS)
        if since < floor:
            since = floor
        since = since - timedelta(hours=WINDOW_OVERLAP_HOURS)

        events: list[dict] = []
        for host in self.sites:
            try:
                events.extend(self._fetch_site(host, since))
            except AtlassianAuthError as e:
                log.warning("skipping %s: %s", host, e)
            except Exception as e:  # noqa: BLE001
                log.exception("confluence fetch failed for %s: %s", host, e)
        log.info("confluence fetch: %d page(s) across %d site(s)",
                 len(events), len(self.sites))
        return events

    def normalize(self, raw: dict) -> dict:
        return raw

    # ------------------------------------------------------------------
    # Per-site fetch
    # ------------------------------------------------------------------

    def _fetch_site(self, host: str, since: datetime) -> Iterable[dict]:
        email, token = auth_for_site(host)
        client = AtlassianClient(host, email, token)

        # CQL date format: yyyy-MM-dd HH:mm
        since_str = since.strftime("%Y-%m-%d %H:%M")
        space_keys = list(self.space_map.keys())
        # Build "space = X OR space = Y OR ..."
        space_clause = " OR ".join(f'space = "{k}"' for k in space_keys)
        cql = (
            f'type = page AND ({space_clause}) AND lastModified >= "{since_str}"'
        )

        params = {
            "cql": cql,
            "expand": "body.storage,version,space,history",
            "limit": MAX_RESULTS,
        }
        data = client.get("/wiki/rest/api/content/search", params=params)
        results = data.get("results", []) or []
        for page in results:
            ev = self._normalize_page(page, host=host)
            if ev is not None:
                yield ev

    def _normalize_page(self, raw: dict, *, host: str) -> dict | None:
        page_id = raw.get("id")
        if not page_id:
            return None
        title = (raw.get("title") or "").strip()
        space = (raw.get("space") or {}).get("key", "")
        if space and space not in self.space_map:
            return None  # space not in our routing — skip

        version = (raw.get("version") or {})
        last_modified = version.get("when") or raw.get("lastModified")

        body_html = ((raw.get("body") or {}).get("storage") or {}).get("value", "")
        body_text = _strip_html(body_html)
        # Truncate aggressively — pages can be huge.
        if len(body_text) > 5000:
            body_text = body_text[:5000] + "\n\n[…truncated]"

        url = self._page_url(host, raw)
        site_slug = slug_for_host(host)

        return {
            "id": f"confluence:{site_slug}:{page_id}",
            "source": "confluence",
            "type": "page",
            "subtype": "updated",
            "timestamp": last_modified or _now_iso(),
            "actorId": f"confluence:{(version.get('by') or {}).get('accountId', '?')}",
            "title": title,
            "body": body_text,
            "url": url,
            "rawData": raw,
            "metadata": {
                "site": host,
                "siteSlug": site_slug,
                "space": space,
                "pageId": page_id,
                "version": version.get("number"),
                "lastModifiedBy": (version.get("by") or {}).get("displayName"),
            },
        }

    def _page_url(self, host: str, raw: dict) -> str:
        links = raw.get("_links") or {}
        webui = links.get("webui")
        if webui:
            base = links.get("base") or f"https://{host}/wiki"
            return base.rstrip("/") + webui
        page_id = raw.get("id", "")
        return f"https://{host}/wiki/spaces/{((raw.get('space') or {}).get('key') or '')}/pages/{page_id}"


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _strip_html(html: str) -> str:
    """Pragmatic HTML → text. Confluence storage format is XHTML-ish."""
    if not html:
        return ""
    text = _HTML_TAG_RE.sub("", html)
    # Decode common entities — full entity expansion isn't needed for the
    # extractor; the model can deal with leftover noise.
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _WHITESPACE_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
