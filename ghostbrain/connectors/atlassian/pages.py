"""Confluence page write operations (create + tracked update)."""
from __future__ import annotations

from ghostbrain.connectors.atlassian._base import AtlassianClient, AtlassianNotFound


class PageGone(RuntimeError):
    """The tracked page no longer exists on Confluence."""


def _page_url(data: dict) -> str:
    links = data.get("_links") or {}
    return f"{links.get('base', '')}{links.get('webui', '')}"


def create_page(
    client: AtlassianClient,
    *,
    space_key: str,
    title: str,
    storage_html: str,
    parent_id: str | None = None,
) -> dict:
    body = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    if parent_id:
        body["ancestors"] = [{"id": parent_id}]
    data = client.post("/wiki/rest/api/content", body)
    return {"page_id": str(data["id"]), "url": _page_url(data)}


def update_page(
    client: AtlassianClient, *, page_id: str, title: str, storage_html: str
) -> dict:
    try:
        current = client.get(f"/wiki/rest/api/content/{page_id}", params={"expand": "version"})
    except AtlassianNotFound as e:
        raise PageGone(page_id) from e
    version = int(((current.get("version") or {}).get("number")) or 1) + 1
    body = {
        "id": page_id,
        "type": "page",
        "title": title,
        "version": {"number": version},
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    data = client.put(f"/wiki/rest/api/content/{page_id}", body)
    return {"page_id": str(data["id"]), "url": _page_url(data)}
