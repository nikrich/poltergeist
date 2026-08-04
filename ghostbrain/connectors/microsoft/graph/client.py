"""Thin Microsoft Graph REST client. Holds a bearer token, does GETs and
@odata.nextLink paging. Keeps connector fetch logic free of HTTP plumbing
and trivial to unit-test with a mocked `requests`."""

from __future__ import annotations

import logging

import requests

from ghostbrain.connectors.microsoft.graph.auth import GRAPH, MicrosoftAuthError

log = logging.getLogger("ghostbrain.connectors.microsoft.client")

DEFAULT_TIMEOUT_S = 30


class GraphClient:
    def __init__(self, token: str, *, timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
        self._token = token
        self._timeout = timeout_s

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"}

    def _request(self, url: str, params: dict | None) -> dict:
        r = requests.get(
            url, headers=self._headers(), params=params, timeout=self._timeout
        )
        if r.status_code == 401:
            raise MicrosoftAuthError(
                "Graph returned 401 (token expired/revoked). "
                "Re-run: ghostbrain-microsoft-auth"
            )
        r.raise_for_status()
        return r.json()

    def get(self, path: str, params: dict | None = None) -> dict:
        """GET a single Graph resource. `path` is relative ('/me/messages')
        or an absolute Graph URL (used internally for nextLink)."""
        url = path if path.startswith("http") else f"{GRAPH}{path}"
        return self._request(url, params)

    def get_all(
        self, path: str, params: dict | None = None, *, max_items: int | None = None
    ) -> list:
        """GET and follow @odata.nextLink, accumulating `value` arrays.
        Stops once `max_items` is reached (None = no cap)."""
        items: list = []
        body = self.get(path, params)
        while True:
            items.extend(body.get("value") or [])
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]
            next_link = body.get("@odata.nextLink")
            if not next_link:
                return items
            body = self.get(next_link)  # nextLink already carries params
