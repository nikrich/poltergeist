"""Atlassian Cloud HTTP client + auth helpers.

Tokens are read from the environment so they never enter source or vault.

For a site like ``sft.atlassian.net`` the connector will look for:
    1. ``ATLASSIAN_TOKEN_SFT`` (preferred — site-specific)
    2. ``ATLASSIAN_TOKEN``    (fallback — single-token setups)

``ATLASSIAN_EMAIL`` is required.
"""

from __future__ import annotations

import logging
import os
import time
from base64 import b64encode

import requests

log = logging.getLogger("ghostbrain.connectors.atlassian")

DEFAULT_TIMEOUT_S = 30
RETRY_STATUSES = {500, 502, 503, 504}


class AtlassianAuthError(RuntimeError):
    pass


class AtlassianClient:
    """Thin wrapper around requests.Session for one Atlassian site.

    Handles Basic auth, rate-limit backoff (429), and 5xx retries.
    """

    def __init__(self, host: str, email: str, token: str) -> None:
        self.host = host
        self._session = requests.Session()
        cred = b64encode(f"{email}:{token}".encode("utf-8")).decode("ascii")
        self._session.headers.update({
            "Authorization": f"Basic {cred}",
            "Accept": "application/json",
            "User-Agent": "ghostbrain/0.1 (atlassian-connector)",
        })

    def get(
        self,
        path: str,
        params: dict | None = None,
        *,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = 3,
    ) -> dict:
        url = self._url(path)
        last_status: int | None = None
        last_text: str = ""
        for attempt in range(max_retries):
            try:
                response = self._session.get(url, params=params, timeout=timeout_s)
            except requests.RequestException as e:
                log.warning("atlassian GET %s attempt %d failed: %s",
                            path, attempt + 1, e)
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
                continue

            last_status = response.status_code
            last_text = (response.text or "")[:200]

            if response.status_code == 429:
                wait = _retry_after_seconds(response, default=5)
                log.info("atlassian rate-limited, sleeping %ds", wait)
                time.sleep(wait)
                continue

            if response.status_code in RETRY_STATUSES:
                log.warning("atlassian %d on attempt %d, backing off",
                            response.status_code, attempt + 1)
                time.sleep(2 ** attempt)
                continue

            if response.status_code == 401:
                raise AtlassianAuthError(
                    f"401 from {url}. Check ATLASSIAN_EMAIL and the relevant "
                    "ATLASSIAN_TOKEN_* env var."
                )

            response.raise_for_status()
            return response.json()

        raise RuntimeError(
            f"atlassian GET {url} failed after {max_retries} retries "
            f"(last status={last_status}, body={last_text!r})"
        )

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"https://{self.host}{path}"


def auth_for_site(host: str) -> tuple[str, str]:
    """Return ``(email, token)`` for the given Atlassian host.

    Raises ``AtlassianAuthError`` when env vars are missing.
    """
    email = os.environ.get("ATLASSIAN_EMAIL")
    if not email:
        raise AtlassianAuthError(
            "ATLASSIAN_EMAIL not set. Add it to .env or your shell."
        )

    slug = slug_for_host(host).upper().replace("-", "_")
    site_var = f"ATLASSIAN_TOKEN_{slug}"
    token = os.environ.get(site_var) or os.environ.get("ATLASSIAN_TOKEN")
    if not token:
        raise AtlassianAuthError(
            f"{site_var} (or ATLASSIAN_TOKEN) not set. Generate an Atlassian "
            "API token at https://id.atlassian.com/manage-profile/security/api-tokens "
            "and add it to .env."
        )
    return (email, token)


def slug_for_host(host: str) -> str:
    """Extract the site slug from an Atlassian host.

    ``sft.atlassian.net`` → ``sft``.
    """
    return host.split(".", 1)[0]


def _retry_after_seconds(response: "requests.Response", *, default: int) -> int:
    raw = response.headers.get("Retry-After")
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default
