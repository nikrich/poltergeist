"""Export a jot to Confluence: create a page, or update the page we created.

Frontmatter is the tracking store: ``confluence_page_id`` decides create vs
update. Frontmatter is only stamped AFTER the Atlassian call succeeded.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ghostbrain.api.repo import notes_manual
from ghostbrain.api.repo.import_atlassian import (
    CONFLUENCE_NOT_CONFIGURED,
    _client,
    _confluence_config,
    _load_routing,
)
from ghostbrain.connectors.atlassian import pages
from ghostbrain.connectors.atlassian.markdown_out import to_storage_html

log = logging.getLogger("ghostbrain.export_confluence")

_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)


class TrackedPageGone(RuntimeError):
    """Tracked confluence_page_id 404s remotely. Route maps to HTTP 409."""


def _title_for(jot: dict, override: str | None) -> str:
    if override:
        return override
    m = _H1.search(jot["body"])
    return m.group(1).strip() if m else jot["title"]


def _client_for_space(space_key: str):
    routing = _load_routing()
    sites, _spaces = _confluence_config(routing)
    # v1 always uses the first configured site (single-site setups are the
    # norm); space_key only goes into the API payload, never site selection.
    host = sites[0]
    return _client(host, not_configured=CONFLUENCE_NOT_CONFIGURED)


def export_jot(
    jot_id: str,
    *,
    space_key: str,
    parent_id: str | None,
    title: str | None,
    force_new: bool,
) -> dict:
    jot = notes_manual.read_jot(jot_id)  # raises JotNotFound → route 404
    client = _client_for_space(space_key)
    storage = to_storage_html(jot["body"])
    page_title = _title_for(jot, title)
    tracked = None if force_new else jot["frontmatter"].get("confluence_page_id")

    if tracked:
        try:
            result = pages.update_page(
                client, page_id=str(tracked), title=page_title, storage_html=storage
            )
            action = "updated"
        except pages.PageGone as e:
            raise TrackedPageGone(str(tracked)) from e
    else:
        result = pages.create_page(
            client,
            space_key=space_key,
            title=page_title,
            storage_html=storage,
            parent_id=parent_id,
        )
        action = "created"

    notes_manual.set_frontmatter_fields(jot_id, {
        "confluence_page_id": result["page_id"],
        "confluence_space": space_key,
        "confluence_url": result["url"],
        "confluence_exported_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"action": action, "page_id": result["page_id"], "url": result["url"]}
