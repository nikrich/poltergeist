"""Browse + import Confluence pages and Jira issues on demand.

Wraps the existing AtlassianClient and the connectors' module-level
normalization functions (extracted in the Task-1 refactor) so imported notes
are identical to scheduled-sync notes. Browse functions are read-only;
``import_items`` (the write half) persists + routes inline via the worker
pipeline — see its docstring.
"""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ghostbrain.connectors.atlassian._base import (
    AtlassianAuthError,
    AtlassianClient,
    auth_for_site,
    slug_for_host,
)
from ghostbrain.connectors.confluence import PAGE_EXPAND, normalize_page
from ghostbrain.connectors.jira import JQL_FIELDS, MY_ISSUES_JQL, normalize_issue
from ghostbrain.paths import vault_path

log = logging.getLogger("ghostbrain.api.repo.import_atlassian")

CONFLUENCE_NOT_CONFIGURED = "confluence connector not configured — run onboarding"
JIRA_NOT_CONFIGURED = "jira connector not configured — run onboarding"
# Browse lists only need the row fields, not full descriptions.
BROWSE_FIELDS = "summary,status,project,updated"
DEFAULT_LIMIT = 25


class ImportNotConfiguredError(RuntimeError):
    """The relevant connector has no sites/spaces in routing.yaml, or its
    auth env vars are missing. Routes translate this to HTTP 409."""


# ──────────────────────────────────────────────────────────────────────────
# Config + auth
# ──────────────────────────────────────────────────────────────────────────

def _load_routing() -> dict:
    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    return yaml.safe_load(f.read_text(encoding="utf-8")) or {}


def _confluence_config(routing: dict) -> tuple[list[str], dict[str, str]]:
    cfg = routing.get("confluence") or {}
    # Confluence shares Atlassian sites with Jira when not configured
    # explicitly — same fallback as the scheduled runner's _build().
    sites = list(cfg.get("sites") or (routing.get("jira") or {}).get("sites") or [])
    spaces = dict(cfg.get("spaces") or {})
    if not sites or not spaces:
        raise ImportNotConfiguredError(CONFLUENCE_NOT_CONFIGURED)
    return sites, spaces


def _jira_sites(routing: dict) -> list[str]:
    sites = list((routing.get("jira") or {}).get("sites") or {})
    if not sites:
        raise ImportNotConfiguredError(JIRA_NOT_CONFIGURED)
    return sites


def _client(host: str, *, not_configured: str) -> AtlassianClient:
    try:
        email, token = auth_for_site(host)
    except AtlassianAuthError as e:
        # Missing env auth is a configuration problem (409), never a 500.
        log.info("atlassian auth missing for %s: %s", host, e)
        raise ImportNotConfiguredError(not_configured) from e
    return AtlassianClient(host, email, token)


# ──────────────────────────────────────────────────────────────────────────
# Browse (read-only)
# ──────────────────────────────────────────────────────────────────────────

def list_spaces() -> list[dict]:
    """Monitored spaces from routing.yaml, with best-effort display names."""
    routing = _load_routing()
    sites, spaces = _confluence_config(routing)
    out: list[dict] = []
    for host in sites:
        client = _client(host, not_configured=CONFLUENCE_NOT_CONFIGURED)
        names = _space_names(client, list(spaces.keys()))
        slug = slug_for_host(host)
        for key, context in spaces.items():
            out.append({
                "site": host,
                "siteSlug": slug,
                "key": key,
                "name": names.get(key, key),
                "context": context,
            })
    return out


def _space_names(client: AtlassianClient, keys: list[str]) -> dict[str, str]:
    """Best-effort key→display-name lookup; callers fall back to the key."""
    try:
        data = client.get(
            "/wiki/rest/api/space",
            params={"spaceKey": keys, "limit": max(len(keys), 1)},
        )
    except Exception as e:  # noqa: BLE001 — names are cosmetic
        log.warning("confluence space-name lookup failed: %s", e)
        return {}
    return {
        s["key"]: (s.get("name") or s["key"])
        for s in (data.get("results") or [])
        if isinstance(s, dict) and s.get("key")
    }


def list_confluence_pages(
    site: str,
    space: str,
    parent: str | None = None,
    limit: int = DEFAULT_LIMIT,
    cursor: str | None = None,
) -> dict:
    """Top-level pages of a monitored space, or children of ``parent``."""
    if parent is not None and not parent.isdigit():
        # parent is interpolated into the API URL path — numeric page ids only.
        raise ValueError(f"invalid parent page id: {parent!r}")
    routing = _load_routing()
    sites, spaces = _confluence_config(routing)
    if site not in sites:
        raise ValueError(f"unknown confluence site: {site}")
    if space not in spaces:
        raise ValueError(f"space not monitored: {space}")
    start = int(cursor) if cursor and cursor.isdigit() else 0
    client = _client(site, not_configured=CONFLUENCE_NOT_CONFIGURED)
    params: dict = {
        "expand": "version,children.page",
        "limit": limit,
        "start": start,
    }
    if parent:
        data = client.get(f"/wiki/rest/api/content/{parent}/child/page", params=params)
    else:
        data = client.get(
            f"/wiki/rest/api/space/{space}/content/page",
            params={**params, "depth": "root"},
        )
    results = data.get("results") or []
    items = [
        _page_row(raw, site=site, space=space, parent_id=parent)
        for raw in results
    ]
    next_cursor = str(start + limit) if len(results) >= limit else None
    return {"items": items, "nextCursor": next_cursor}


def search_confluence(q: str, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """CQL ``title ~ q`` across the monitored spaces of every site."""
    routing = _load_routing()
    sites, spaces = _confluence_config(routing)
    quoted = q.replace('"', '\\"')
    space_clause = " OR ".join(f'space = "{k}"' for k in spaces)
    cql = f'type = page AND ({space_clause}) AND title ~ "{quoted}"'
    out: list[dict] = []
    for host in sites:
        client = _client(host, not_configured=CONFLUENCE_NOT_CONFIGURED)
        data = client.get(
            "/wiki/rest/api/content/search",
            params={"cql": cql, "expand": "version,space,children.page",
                    "limit": limit},
        )
        for raw in data.get("results") or []:
            out.append(_page_row(raw, site=host, space=None, parent_id=None))
    return out[:limit]


def _page_row(
    raw: dict, *, site: str, space: str | None, parent_id: str | None
) -> dict:
    version = raw.get("version") or {}
    children = (raw.get("children") or {}).get("page") or {}
    return {
        "site": site,
        "id": str(raw.get("id") or ""),
        "title": raw.get("title") or "",
        "parentId": parent_id,
        "hasChildren": int(children.get("size") or 0) > 0,
        "updatedAt": version.get("when"),
        "version": version.get("number"),
        "space": space or ((raw.get("space") or {}).get("key") or None),
    }


def list_jira_issues(q: str | None = None, limit: int = DEFAULT_LIMIT) -> list[dict]:
    """No ``q``: the connector's my-issues JQL, newest first. With ``q``:
    ``text ~ q`` within the configured sites."""
    routing = _load_routing()
    sites = _jira_sites(routing)
    if q and q.strip():
        quoted = q.strip().replace('"', '\\"')
        jql = f'text ~ "{quoted}" ORDER BY updated DESC'
    else:
        jql = f"{MY_ISSUES_JQL} ORDER BY updated DESC"
    out: list[dict] = []
    for host in sites:
        client = _client(host, not_configured=JIRA_NOT_CONFIGURED)
        params = {"jql": jql, "fields": BROWSE_FIELDS, "maxResults": limit}
        try:
            data = client.get("/rest/api/3/search/jql", params=params)
        except Exception as e:  # noqa: BLE001 — same fallback as the connector
            log.info("falling back to legacy /search for %s: %s", host, e)
            data = client.get("/rest/api/3/search", params=params)
        for raw in data.get("issues") or []:
            fields = raw.get("fields") or {}
            out.append({
                "site": host,
                "key": raw.get("key") or "",
                "summary": (fields.get("summary") or "").strip(),
                "status": (fields.get("status") or {}).get("name"),
                "project": (fields.get("project") or {}).get("key"),
                "updatedAt": fields.get("updated"),
            })
    out.sort(key=lambda r: r["updatedAt"] or "", reverse=True)
    return out[:limit]
