# ghostbrain/mcp/client.py
"""Discover and call the running Poltergeist sidecar over local HTTP."""
from __future__ import annotations

from typing import Any, Callable

import httpx

from ghostbrain.api.runtime import load_descriptor

NOT_RUNNING_MESSAGE = "Poltergeist isn't running — open the Poltergeist app to start it."

# answer can take ~5-15s on sonnet; allow generous headroom.
DEFAULT_TIMEOUT = 60.0


class SidecarNotRunning(RuntimeError):
    """Raised when no live sidecar can be reached."""


class SidecarClient:
    """Thin HTTP client bound to the sidecar advertised by the descriptor."""

    def __init__(
        self,
        *,
        loader: Callable[[], dict | None] = load_descriptor,
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._loader = loader
        self._http = http_client or httpx.Client(timeout=timeout)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        descriptor = self._loader()
        if not descriptor:
            raise SidecarNotRunning(NOT_RUNNING_MESSAGE)
        url = f"http://127.0.0.1:{descriptor['port']}{path}"
        headers = {"Authorization": f"Bearer {descriptor['token']}"}
        try:
            resp = self._http.request(method, url, headers=headers, **kwargs)
        except httpx.ConnectError as e:
            raise SidecarNotRunning(NOT_RUNNING_MESSAGE) from e
        resp.raise_for_status()
        return resp.json()

    def answer(self, q: str, limit: int = 8) -> dict:
        return self._request("POST", "/v1/answer", json={"q": q, "limit": limit})

    def search(self, q: str, limit: int = 10, days: int | None = None) -> dict:
        payload: dict = {"q": q, "limit": limit}
        if days is not None:
            payload["days"] = days
        return self._request("POST", "/v1/search", json=payload)

    def get_note(self, path: str) -> dict:
        return self._request("GET", "/v1/notes", params={"path": path})

    def write_doc(self, title: str, html: str) -> dict:
        return self._request("POST", "/v1/docs/write", json={"title": title, "html": html})
