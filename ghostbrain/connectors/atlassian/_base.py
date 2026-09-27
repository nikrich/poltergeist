"""Atlassian Cloud HTTP client + auth helpers.

Tokens never enter source or vault. For a site like ``acme.atlassian.net``:

Email: the site's account in accounts.yaml (``options.email``, jira then
confluence) → ``ATLASSIAN_EMAIL``.

Token: ``ATLASSIAN_TOKEN_ACME`` (preferred — site-specific env var) →
``state/atlassian.acme.token`` (site-specific file, written by ``save_token``)
→ ``ATLASSIAN_TOKEN`` (fallback — single-token setups).
"""

from __future__ import annotations

import logging
import os
import time
from base64 import b64encode
from pathlib import Path

import requests

log = logging.getLogger("ghostbrain.connectors.atlassian")

DEFAULT_TIMEOUT_S = 30
RETRY_STATUSES = {500, 502, 503, 504}


class AtlassianAuthError(RuntimeError):
    pass


class AtlassianNotFound(RuntimeError):
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

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | None = None,
        *,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = 3,
    ) -> dict:
        url = self._url(path)
        last_status: int | None = None
        last_text: str = ""
        for attempt in range(max_retries):
            try:
                response = self._session.request(
                    method, url, params=params, json=json_body, timeout=timeout_s
                )
            except requests.RequestException as e:
                log.warning(
                    "atlassian %s %s attempt %d failed: %s",
                    method, path, attempt + 1, e,
                )
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)
                continue

            last_status = response.status_code
            last_text = (response.text or "")[:200]

            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait = _retry_after_seconds(response, default=5)
                    log.info("atlassian rate-limited, sleeping %ds", wait)
                    time.sleep(wait)
                continue

            if response.status_code in RETRY_STATUSES:
                if attempt < max_retries - 1:
                    log.warning(
                        "atlassian %d on attempt %d, backing off",
                        response.status_code, attempt + 1,
                    )
                    time.sleep(2 ** attempt)
                continue

            if response.status_code == 401:
                raise AtlassianAuthError(
                    f"401 from {url}. Check ATLASSIAN_EMAIL and the relevant "
                    "ATLASSIAN_TOKEN_* env var."
                )

            if response.status_code == 404:
                raise AtlassianNotFound(
                    f"404 from {url}."
                )

            response.raise_for_status()
            return response.json()

        raise RuntimeError(
            f"atlassian {method} {url} failed after {max_retries} retries "
            f"(last status={last_status}, body={last_text!r})"
        )

    def get(
        self,
        path: str,
        params: dict | None = None,
        *,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = 3,
    ) -> dict:
        return self._request("GET", path, params=params, timeout_s=timeout_s, max_retries=max_retries)

    def post(self, path: str, json_body: dict, *, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
        return self._request("POST", path, json_body=json_body, timeout_s=timeout_s, max_retries=1)

    def put(self, path: str, json_body: dict, *, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
        return self._request("PUT", path, json_body=json_body, timeout_s=timeout_s, max_retries=1)

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"https://{self.host}{path}"


def auth_for_site(host: str) -> tuple[str, str]:
    """Return ``(email, token)`` for the given Atlassian host.

    Email: the site's account in accounts.yaml (``options.email``, jira then
    confluence) → ``ATLASSIAN_EMAIL``. Token: ``ATLASSIAN_TOKEN_<SLUG>`` →
    ``state/atlassian.<slug>.token`` → ``ATLASSIAN_TOKEN``. The site-specific
    file wins over the global env token so an old single-agency token can't
    shadow another agency's site.

    Raises ``AtlassianAuthError`` when either is missing.
    """
    email = _registry_email(host) or os.environ.get("ATLASSIAN_EMAIL")
    if not email:
        raise AtlassianAuthError(
            f"No Atlassian email for {host}. Reconnect the site in the app, or set "
            "ATLASSIAN_EMAIL in .env."
        )

    slug = slug_for_host(host).upper().replace("-", "_")
    site_var = f"ATLASSIAN_TOKEN_{slug}"
    token = os.environ.get(site_var) or _read_token_file(host) or os.environ.get("ATLASSIAN_TOKEN")
    if not token:
        raise AtlassianAuthError(
            f"No API token for {host} ({site_var}, {token_path(host)}, or ATLASSIAN_TOKEN). "
            "Generate one at https://id.atlassian.com/manage-profile/security/api-tokens "
            "and reconnect the site in the app."
        )
    return (email, token)


def token_path(host: str) -> Path:
    from ghostbrain.paths import state_dir

    return state_dir() / f"atlassian.{slug_for_host(host).lower()}.token"


def save_token(host: str, token: str) -> Path:
    p = token_path(host)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token.strip(), encoding="utf-8")
    p.chmod(0o600)
    return p


def _read_token_file(host: str) -> str | None:
    try:
        return token_path(host).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _registry_email(host: str) -> str | None:
    from ghostbrain import accounts

    for connector in ("jira", "confluence"):
        acc = accounts.get_account(connector, host)
        if acc is not None and acc.options.get("email"):
            return str(acc.options["email"])
    return None


def slug_for_host(host: str) -> str:
    """Extract the site slug from an Atlassian host.

    ``acme.atlassian.net`` → ``acme``.
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
