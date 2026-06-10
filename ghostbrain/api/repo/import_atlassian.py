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
from ghostbrain.worker.audit import audit_log

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


# ──────────────────────────────────────────────────────────────────────────
# Import (write)
# ──────────────────────────────────────────────────────────────────────────

def import_items(items: list[dict]) -> list[dict]:
    """Import each item sequentially; a failed item never aborts the batch.

    Mechanism (mirrors the scheduled pipeline exactly): the scheduled sync
    enqueues normalized events into 90-meta/queue/pending and the worker's
    run_loop feeds each one to ghostbrain.worker.pipeline.process_event,
    which routes (path-first, LLM fallback) and persists via write_note.
    Import skips the queue hop and calls process_event inline on the same
    normalized event — identical frontmatter, body, filename, and routing
    fallback (low confidence → inbox manual_review), one call per item.

    Raises ImportNotConfiguredError (→ 409) up front when the connector for
    any requested kind has no routing config or no auth env vars. Everything
    after that is per-item: failures become {"ok": False, "error": ...}.
    """
    routing = _load_routing()
    kinds = {i.get("kind") for i in items}
    # Validate config + auth BEFORE touching any item (spec: 409, not a
    # batch of per-item failures). auth_for_site only reads env vars.
    if "confluence_page" in kinds:
        sites, _spaces = _confluence_config(routing)
        _client(sites[0], not_configured=CONFLUENCE_NOT_CONFIGURED)
    if "jira_issue" in kinds:
        jira_sites = _jira_sites(routing)
        _client(jira_sites[0], not_configured=JIRA_NOT_CONFIGURED)
    return [_import_one(item, routing) for item in items]


def _import_one(item: dict, routing: dict) -> dict:
    kind = item.get("kind")
    ident: dict = {"kind": kind}
    if kind == "confluence_page":
        ident["id"] = item.get("id")
    else:
        ident["key"] = item.get("key")
    try:
        event = _fetch_event(item, routing)
        existing = _existing_note_paths(event["id"], source=event["source"])
        summary = _process(event)
        written = {
            str(Path(p).resolve())
            for p in (summary.get("inbox_path"), summary.get("context_path"))
            if p
        }
        for old in existing:
            if str(old.resolve()) not in written:
                # The connector filename embeds timestamp+title; an item that
                # changed since its last sync/import lands at a NEW filename.
                # Remove the stale copy so re-import updates, not duplicates.
                old.unlink(missing_ok=True)
        path = summary.get("context_path") or summary.get("inbox_path")
        rel = _vault_relative(path)
        audit_log(
            "import_completed",
            event["id"],
            source=event["source"],
            ok=True,
            context=summary.get("context"),
            path=rel,
        )
        return {
            **ident,
            "ok": True,
            "path": rel,
            "context": summary.get("context"),
            "updated": bool(existing),
        }
    except Exception as e:  # noqa: BLE001 — per-item isolation is the contract
        log.warning("import failed for %s: %s", ident, e)
        audit_log(
            "import_completed",
            ident.get("id") or ident.get("key") or "?",
            source="confluence" if kind == "confluence_page" else "jira",
            ok=False,
            error=str(e),
        )
        return {**ident, "ok": False, "error": str(e)}


def _fetch_event(item: dict, routing: dict) -> dict:
    """Fetch full content for one item and run the connector's conversion."""
    kind = item.get("kind")
    host = item.get("site") or ""
    if kind == "confluence_page":
        _sites, spaces = _confluence_config(routing)
        client = _client(host, not_configured=CONFLUENCE_NOT_CONFIGURED)
        raw = client.get(
            f"/wiki/rest/api/content/{item['id']}",
            params={"expand": PAGE_EXPAND},
        )
        event = normalize_page(raw, host=host, space_map=spaces)
        if event is None:
            raise ValueError(
                "page is not importable (missing id or unmonitored space)"
            )
        return event
    if kind == "jira_issue":
        _jira_sites(routing)
        client = _client(host, not_configured=JIRA_NOT_CONFIGURED)
        raw = client.get(
            f"/rest/api/3/issue/{item['key']}",
            params={"fields": JQL_FIELDS},
        )
        return normalize_issue(raw, host=host)
    raise ValueError(f"unknown import kind: {kind}")


def _process(event: dict) -> dict:
    # Imported lazily: the pipeline pulls in the claude-code parser, the LLM
    # client, and the extractor — none of which the browse endpoints need.
    from ghostbrain.worker.pipeline import process_event

    return process_event(event)


def _existing_note_paths(note_id: str, *, source: str) -> list[Path]:
    """All vault notes whose frontmatter id matches this event id.

    Searched in the same places write_note writes: the durable inbox and the
    per-context source dirs (jira notes live under jira/tickets/)."""
    vault = vault_path()
    sub = "jira/tickets" if source == "jira" else source
    dirs = [vault / "00-inbox" / "raw" / source]
    dirs.extend(sorted((vault / "20-contexts").glob(f"*/{sub}")))
    found: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            if _frontmatter_id(p) == note_id:
                found.append(p)
    return found


def _frontmatter_id(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        fm = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return fm.get("id") if isinstance(fm, dict) else None


def _vault_relative(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(vault_path().resolve()))
    except ValueError:
        return str(path)
