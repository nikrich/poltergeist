"""Jira Cloud connector. Fetches tickets the user is involved in
(assignee, reporter, watcher) that have been updated recently."""

from __future__ import annotations

import logging
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

log = logging.getLogger("ghostbrain.connectors.jira")

# How far back to look on first run (no last_run state file yet).
FIRST_RUN_LOOKBACK_HOURS = 24
# Buffer added to last_run window so an event updated right before the
# previous fetch isn't missed.
WINDOW_OVERLAP_HOURS = 1
# Cap per-site fetch.
MAX_RESULTS = 50

JQL_FIELDS = (
    "summary,status,assignee,reporter,priority,issuetype,labels,project,"
    "created,updated,description,resolution"
)


class JiraConnector(Connector):
    """One connector instance, multiple sites — runs through each site
    sequentially. Each site uses its own auth pair from the env."""

    name = "jira"
    version = "1.0"

    def __init__(
        self,
        config: dict,
        queue_dir: Path,
        state_dir: Path,
    ) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.sites: list[str] = list(config.get("sites") or [])
        self.lookback_hours = int(config.get("lookback_hours") or 4)

    def health_check(self) -> bool:
        if not self.sites:
            return False
        try:
            for host in self.sites:
                email, token = auth_for_site(host)
                client = AtlassianClient(host, email, token)
                client.get("/rest/api/3/myself")
        except (AtlassianAuthError, Exception) as e:
            log.warning("jira health check failed: %s", e)
            return False
        return True

    def fetch(self, since: datetime) -> list[dict]:
        if not self.sites:
            log.info("no jira sites configured; skipping fetch")
            return []

        floor = datetime.now(timezone.utc) - timedelta(hours=FIRST_RUN_LOOKBACK_HOURS)
        if since < floor:
            since = floor
        # Apply overlap buffer in case events came in just before the last run.
        since = since - timedelta(hours=WINDOW_OVERLAP_HOURS)

        events: list[dict] = []
        for host in self.sites:
            try:
                events.extend(self._fetch_site(host, since))
            except AtlassianAuthError as e:
                log.warning("skipping %s: %s", host, e)
            except Exception as e:  # noqa: BLE001
                log.exception("jira fetch failed for %s: %s", host, e)
        log.info("jira fetch: %d event(s) across %d site(s)",
                 len(events), len(self.sites))
        return events

    def normalize(self, raw: dict) -> dict:
        # `_fetch_site` already produces normalized events.
        return raw

    # ------------------------------------------------------------------
    # Per-site fetch
    # ------------------------------------------------------------------

    def _fetch_site(self, host: str, since: datetime) -> Iterable[dict]:
        email, token = auth_for_site(host)
        client = AtlassianClient(host, email, token)

        # Atlassian's JQL date format wants "yyyy-MM-dd HH:mm".
        since_str = since.strftime("%Y-%m-%d %H:%M")
        jql = (
            f'(assignee = currentUser() OR reporter = currentUser() '
            f'OR watcher = currentUser()) AND updated >= "{since_str}"'
        )

        # Atlassian recommends /search/jql (token-paginated) but the classic
        # /search still works on Cloud. We use the new endpoint.
        params = {
            "jql": jql,
            "fields": JQL_FIELDS,
            "maxResults": MAX_RESULTS,
        }
        try:
            data = client.get("/rest/api/3/search/jql", params=params)
        except Exception as e:  # noqa: BLE001
            # Fall back to legacy endpoint if the new one is blocked.
            log.info("falling back to legacy /search for %s: %s", host, e)
            data = client.get("/rest/api/3/search", params=params)

        issues = data.get("issues", []) or []
        for issue in issues:
            yield self._normalize_issue(issue, host=host)

    def _normalize_issue(self, raw: dict, *, host: str) -> dict:
        fields = raw.get("fields") or {}
        key = raw.get("key", "?")
        summary = (fields.get("summary") or "").strip()
        status_obj = fields.get("status") or {}
        priority_obj = fields.get("priority") or {}
        assignee_obj = fields.get("assignee") or {}
        reporter_obj = fields.get("reporter") or {}
        project = (fields.get("project") or {}).get("key", "")

        site_slug = slug_for_host(host)

        return {
            "id": f"jira:{site_slug}:{key}",
            "source": "jira",
            "type": "ticket",
            "subtype": (status_obj.get("name") or "").lower() or "open",
            "timestamp": fields.get("updated") or fields.get("created") or _now_iso(),
            "actorId": f"jira:{(reporter_obj or {}).get('accountId', '?')}",
            "title": f"{key} {summary}".strip(),
            "body": _adf_to_text(fields.get("description")) or "",
            "url": f"https://{host}/browse/{key}",
            "rawData": raw,
            "metadata": {
                "site": host,
                "siteSlug": site_slug,
                "project": project,
                "key": key,
                "status": status_obj.get("name"),
                "statusCategory": (status_obj.get("statusCategory") or {}).get("key"),
                "priority": priority_obj.get("name"),
                "assignee": (assignee_obj or {}).get("displayName"),
                "reporter": (reporter_obj or {}).get("displayName"),
                "labels": fields.get("labels") or [],
                "issueType": ((fields.get("issuetype") or {}) or {}).get("name"),
            },
        }


def _adf_to_text(adf: Any) -> str:
    """Flatten an Atlassian Document Format value to plain text.

    Jira returns rich-text descriptions in ADF. Full conversion is non-
    trivial; we just walk the tree and concatenate text leaves so the
    extractor / digest get something readable.
    """
    if adf is None:
        return ""
    if isinstance(adf, str):
        return adf
    if isinstance(adf, dict):
        if adf.get("type") == "text" and isinstance(adf.get("text"), str):
            return adf["text"]
        children = adf.get("content") or []
        return "".join(_adf_to_text(c) for c in children)
    if isinstance(adf, list):
        return "\n".join(_adf_to_text(c) for c in adf)
    return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
