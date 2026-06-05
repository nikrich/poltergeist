# Microsoft 365 Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest Outlook mail, Teams chat messages, and Teams meeting transcripts from the work Microsoft 365 tenant into Poltergeist's event queue as three sibling connectors sharing one Microsoft Graph device-code auth core.

**Architecture:** A new `ghostbrain/connectors/microsoft/` family. A shared `graph/` sub-package holds MSAL device-code auth (keychain-cached) and a thin Graph HTTP client. Three connectors (`outlook_mail`, `teams_chat`, `teams_meetings`) each subclass the existing `Connector` base, with their own routing key, schedule cadence, and `.last_run` dedup. Mail and chat run a shared LLM relevance gate; transcripts are pulled deliberately via calendar walk and are not gated.

**Tech Stack:** Python 3.11+, `msal` + `msal-extensions` (delegated device-code auth + OS keychain token cache), `requests` (Graph REST), existing `ghostbrain.llm.client` (Haiku relevance gate), pytest with `unittest.mock`.

**Reference design:** `docs/superpowers/specs/2026-06-04-microsoft-365-connector-design.md`

---

## File Structure

**Create:**
- `ghostbrain/connectors/microsoft/__init__.py` — package marker
- `ghostbrain/connectors/microsoft/graph/__init__.py` — package marker
- `ghostbrain/connectors/microsoft/graph/auth.py` — MSAL device-code flow, keychain cache, `get_token`, `MicrosoftAuthError`
- `ghostbrain/connectors/microsoft/graph/auth_cli.py` — `ghostbrain-microsoft-auth` one-time sign-in
- `ghostbrain/connectors/microsoft/graph/client.py` — `GraphClient` GET + paging helper
- `ghostbrain/connectors/_relevance.py` — shared LLM relevance gate used by mail + chat
- `ghostbrain/connectors/microsoft/outlook_mail/{__init__,connector,runner,__main__}.py`
- `ghostbrain/connectors/microsoft/teams_chat/{__init__,connector,runner,__main__}.py`
- `ghostbrain/connectors/microsoft/teams_meetings/{__init__,connector,runner,__main__}.py`
- `tests/test_microsoft_auth.py`
- `tests/test_microsoft_graph_client.py`
- `tests/test_relevance_gate.py`
- `tests/test_outlook_mail_connector.py`
- `tests/test_teams_chat_connector.py`
- `tests/test_teams_meetings_connector.py`

**Modify:**
- `pyproject.toml` — add `msal`, `msal-extensions` deps + 4 console scripts
- `ghostbrain/scheduler_jobs.py` — import 3 runners, register 3 jobs
- `ghostbrain/bootstrap.py` — add 2 relevance prompt files + a `microsoft:` routing.yaml block

**Convention reference (read before starting):** `ghostbrain/connectors/gmail/` is the closest analog for every pattern below (auth, connector, runner, `__main__`, relevance gate). `ghostbrain/connectors/_base.py` defines the `Connector` contract and event shape.

---

## Task 1: Add dependencies and verify the package skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `ghostbrain/connectors/microsoft/__init__.py`, `ghostbrain/connectors/microsoft/graph/__init__.py`

- [ ] **Step 1: Add runtime deps**

In `pyproject.toml`, in the `dependencies` array (where `google-auth-oauthlib>=1.2` lives), add:

```toml
    "msal>=1.28",
    "msal-extensions>=1.1",
    "requests>=2.31",
```

(If `requests` is already listed, do not duplicate it — confirm with `grep -n requests pyproject.toml` first.)

- [ ] **Step 2: Create package markers**

`ghostbrain/connectors/microsoft/__init__.py`:

```python
"""Microsoft 365 connector family (Outlook mail, Teams chat, Teams meeting
transcripts) sharing one Microsoft Graph delegated auth core. See
docs/superpowers/specs/2026-06-04-microsoft-365-connector-design.md."""
```

`ghostbrain/connectors/microsoft/graph/__init__.py`:

```python
"""Shared Microsoft Graph auth + HTTP client for the microsoft connectors."""
```

- [ ] **Step 3: Install into the venv**

Run: `.venv/bin/python -m pip install -e .`
Expected: completes without error; `msal` and `msal_extensions` importable.

Verify: `.venv/bin/python -c "import msal, msal_extensions, requests; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml ghostbrain/connectors/microsoft/__init__.py ghostbrain/connectors/microsoft/graph/__init__.py
git commit -m "build(microsoft): add msal deps and microsoft connector package skeleton"
```

---

## Task 2: Graph auth core (`graph/auth.py`)

**Files:**
- Create: `ghostbrain/connectors/microsoft/graph/auth.py`
- Test: `tests/test_microsoft_auth.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_microsoft_auth.py`:

```python
"""Tests for Microsoft Graph auth helpers. MSAL is mocked — no network,
no device-code flow. Pure path + scope + error logic."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def test_scopes_are_the_union_of_all_three_connectors() -> None:
    from ghostbrain.connectors.microsoft.graph import auth
    assert set(auth.SCOPES) == {
        "Mail.Read",
        "Chat.Read",
        "Calendars.Read",
        "OnlineMeetings.Read",
        "OnlineMeetingTranscript.Read.All",
    }


def test_cache_location_lives_under_state_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    from ghostbrain.connectors.microsoft.graph import auth
    loc = auth.cache_location()
    assert loc == tmp_path / "microsoft" / "token_cache.bin"


def test_resolve_app_config_prefers_routing_over_default() -> None:
    from ghostbrain.connectors.microsoft.graph import auth
    cid, tid = auth.resolve_app_config(
        {"client_id": "cid-override", "tenant_id": "tid-override"}
    )
    assert cid == "cid-override"
    assert tid == "tid-override"


def test_resolve_app_config_falls_back_to_defaults() -> None:
    from ghostbrain.connectors.microsoft.graph import auth
    cid, tid = auth.resolve_app_config({})
    assert cid == auth.DEFAULT_CLIENT_ID
    assert tid == auth.DEFAULT_TENANT_ID


def test_get_token_raises_when_no_cached_account(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    from ghostbrain.connectors.microsoft.graph import auth

    fake_app = MagicMock()
    fake_app.get_accounts.return_value = []
    with patch.object(auth, "_build_app", return_value=fake_app):
        with pytest.raises(auth.MicrosoftAuthError):
            auth.get_token({})


def test_get_token_returns_cached_token_silently(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path))
    from ghostbrain.connectors.microsoft.graph import auth

    fake_app = MagicMock()
    fake_app.get_accounts.return_value = [{"username": "me@example.com"}]
    fake_app.acquire_token_silent.return_value = {"access_token": "tok-123"}
    with patch.object(auth, "_build_app", return_value=fake_app):
        assert auth.get_token({}) == "tok-123"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_microsoft_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: ghostbrain.connectors.microsoft.graph.auth`

- [ ] **Step 3: Implement `graph/auth.py`**

`ghostbrain/connectors/microsoft/graph/auth.py`:

```python
"""Microsoft Graph delegated (device-code) auth.

One device-code sign-in caches a token in the OS keychain
(``msal-extensions`` encrypted persistence) at
``~/.ghostbrain/state/microsoft/token_cache.bin``. All three microsoft
connectors share that cache via the union of scopes below. Scheduled
fetches only ever call ``get_token`` (silent); the interactive device-code
flow lives in ``auth_cli.py``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger("ghostbrain.connectors.microsoft.auth")

# Defaults from the working pull_transcript.py prototype (work tenant).
# Overridable via routing.yaml:microsoft.client_id / .tenant_id.
DEFAULT_CLIENT_ID = "<entra-client-id>"
DEFAULT_TENANT_ID = "<entra-tenant-id>"

# Union of every scope the three connectors need; one consent covers all.
SCOPES = [
    "Mail.Read",
    "Chat.Read",
    "Calendars.Read",
    "OnlineMeetings.Read",
    "OnlineMeetingTranscript.Read.All",
]

GRAPH = "https://graph.microsoft.com/v1.0"


class MicrosoftAuthError(RuntimeError):
    """Raised when Graph credentials are missing, expired beyond refresh,
    or otherwise unusable. Mirrors GmailAuthError."""


def state_dir() -> Path:
    raw = os.environ.get("GHOSTBRAIN_STATE_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".ghostbrain" / "state").resolve()


def cache_location() -> Path:
    return state_dir() / "microsoft" / "token_cache.bin"


def resolve_app_config(config: dict) -> tuple[str, str]:
    """Return (client_id, tenant_id) from routing config, falling back to
    the baked-in prototype defaults."""
    cfg = config or {}
    client_id = str(cfg.get("client_id") or DEFAULT_CLIENT_ID)
    tenant_id = str(cfg.get("tenant_id") or DEFAULT_TENANT_ID)
    return client_id, tenant_id


def _build_token_cache():
    """OS-secure persistent token cache, with a chmod-600 plaintext
    fallback that warns (never a silent downgrade)."""
    from msal_extensions import (
        FilePersistence,
        PersistedTokenCache,
        build_encrypted_persistence,
    )

    loc = cache_location()
    loc.parent.mkdir(parents=True, exist_ok=True)
    try:
        persistence = build_encrypted_persistence(str(loc))
    except Exception as e:  # noqa: BLE001
        log.warning("OS keychain unavailable (%s); using chmod-600 file cache.", e)
        persistence = FilePersistence(str(loc))
        loc.touch(exist_ok=True)
        loc.chmod(0o600)
    return PersistedTokenCache(persistence)


def _build_app(config: dict):
    import msal

    client_id, tenant_id = resolve_app_config(config)
    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.PublicClientApplication(
        client_id, authority=authority, token_cache=_build_token_cache()
    )


def get_token(config: dict) -> str:
    """Return an access token from the cached sign-in. Raises
    MicrosoftAuthError if no usable cached account exists — the interactive
    flow must be run via `ghostbrain-microsoft-auth` first."""
    app = _build_app(config)
    accounts = app.get_accounts()
    if not accounts:
        raise MicrosoftAuthError(
            "No cached Microsoft sign-in. Run: ghostbrain-microsoft-auth"
        )
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise MicrosoftAuthError(
            "Cached Microsoft sign-in could not be refreshed. "
            "Re-run: ghostbrain-microsoft-auth"
        )
    return result["access_token"]


def have_token(config: dict) -> bool:
    """Cheap health-check predicate: True if get_token would succeed."""
    try:
        get_token(config)
        return True
    except MicrosoftAuthError:
        return False


def run_device_flow(config: dict) -> str:
    """Interactive one-time device-code sign-in. Returns the signed-in
    username. Called only from auth_cli.py."""
    app = _build_app(config)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise MicrosoftAuthError(f"Could not start device flow: {flow}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise MicrosoftAuthError(
            f"Auth failed: {result.get('error_description', result)}"
        )
    accounts = app.get_accounts()
    return accounts[0].get("username", "your account") if accounts else "your account"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_microsoft_auth.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/microsoft/graph/auth.py tests/test_microsoft_auth.py
git commit -m "feat(microsoft): graph device-code auth with keychain cache"
```

---

## Task 3: Auth CLI (`graph/auth_cli.py`)

**Files:**
- Create: `ghostbrain/connectors/microsoft/graph/auth_cli.py`

(No unit test — this is a thin interactive wrapper, mirroring `gmail/auth_cli.py` which is also untested. It will be smoke-tested manually at the end.)

- [ ] **Step 1: Implement `graph/auth_cli.py`**

```python
"""Microsoft Graph device-code sign-in CLI.

Usage:
    ghostbrain-microsoft-auth

Runs the one-time device-code flow and caches the token in the OS keychain.
Reads optional client_id/tenant_id from vault/90-meta/routing.yaml:microsoft.
"""

from __future__ import annotations

import logging
import sys

from ghostbrain.connectors.microsoft.graph.auth import (
    MicrosoftAuthError,
    run_device_flow,
)


def _load_microsoft_config() -> dict:
    import yaml

    from ghostbrain.paths import vault_path

    f = vault_path() / "90-meta" / "routing.yaml"
    if not f.exists():
        return {}
    routing = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    return routing.get("microsoft") or {}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        username = run_device_flow(_load_microsoft_config())
    except MicrosoftAuthError as e:
        print(f"auth error: {e}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as e:  # noqa: BLE001
        print(f"unexpected error: {e}", file=sys.stderr)
        raise SystemExit(2)
    print(f"OK — signed in as {username}; token cached.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify it imports**

Run: `.venv/bin/python -c "from ghostbrain.connectors.microsoft.graph.auth_cli import main; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add ghostbrain/connectors/microsoft/graph/auth_cli.py
git commit -m "feat(microsoft): add ghostbrain-microsoft-auth device-code CLI"
```

---

## Task 4: Graph HTTP client (`graph/client.py`)

**Files:**
- Create: `ghostbrain/connectors/microsoft/graph/client.py`
- Test: `tests/test_microsoft_graph_client.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_microsoft_graph_client.py`:

```python
"""Tests for the Graph HTTP client. `requests` is mocked — no network."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def _resp(status, json_body):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body
    return r


def test_get_returns_json_body() -> None:
    from ghostbrain.connectors.microsoft.graph.client import GraphClient

    c = GraphClient("tok")
    with patch("requests.get", return_value=_resp(200, {"value": [1, 2]})) as g:
        out = c.get("/me/messages", params={"$top": 5})
    assert out == {"value": [1, 2]}
    # Bearer header was sent.
    _, kwargs = g.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer tok"


def test_get_401_raises_microsoft_auth_error() -> None:
    from ghostbrain.connectors.microsoft.graph.auth import MicrosoftAuthError
    from ghostbrain.connectors.microsoft.graph.client import GraphClient

    c = GraphClient("tok")
    with patch("requests.get", return_value=_resp(401, {})):
        with pytest.raises(MicrosoftAuthError):
            c.get("/me/messages")


def test_get_all_follows_next_link() -> None:
    from ghostbrain.connectors.microsoft.graph.client import GraphClient

    page1 = _resp(200, {
        "value": [{"id": "a"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=1",
    })
    page2 = _resp(200, {"value": [{"id": "b"}]})

    c = GraphClient("tok")
    with patch("requests.get", side_effect=[page1, page2]):
        items = c.get_all("/me/messages")
    assert [i["id"] for i in items] == ["a", "b"]


def test_get_all_respects_max_items() -> None:
    from ghostbrain.connectors.microsoft.graph.client import GraphClient

    page1 = _resp(200, {
        "value": [{"id": "a"}, {"id": "b"}],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=2",
    })
    c = GraphClient("tok")
    with patch("requests.get", side_effect=[page1]) as g:
        items = c.get_all("/me/messages", max_items=2)
    assert len(items) == 2
    # Stopped after the first page because max_items was reached.
    assert g.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_microsoft_graph_client.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `graph/client.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_microsoft_graph_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/microsoft/graph/client.py tests/test_microsoft_graph_client.py
git commit -m "feat(microsoft): graph http client with paging and 401 handling"
```

---

## Task 5: Shared relevance gate (`connectors/_relevance.py`)

**Files:**
- Create: `ghostbrain/connectors/_relevance.py`
- Test: `tests/test_relevance_gate.py`

This factors out the reusable LLM-gate core (an `llm.run` call with a JSON schema + USD budget, conservative keep-on-error). The Gmail connector is **not** refactored; mail + chat use this new helper.

- [ ] **Step 1: Write the failing tests**

`tests/test_relevance_gate.py`:

```python
"""Tests for the shared relevance gate. The LLM client is mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_apply_gate_keeps_relevant_and_drops_irrelevant() -> None:
    from ghostbrain.connectors._relevance import apply_relevance_gate

    events = [{"id": "1"}, {"id": "2"}]

    def fake_gate(ev):
        return (ev["id"] == "1", "because")

    kept, dropped = apply_relevance_gate(events, fake_gate)
    assert [e["id"] for e in kept] == ["1"]
    assert dropped == 1
    assert kept[0]["metadata"]["relevanceReason"] == "because"


def test_apply_gate_keeps_event_on_gate_error() -> None:
    from ghostbrain.connectors._relevance import apply_relevance_gate

    def boom(ev):
        raise RuntimeError("llm down")

    kept, dropped = apply_relevance_gate([{"id": "1"}], boom)
    assert [e["id"] for e in kept] == ["1"]  # conservative: kept
    assert dropped == 0


def test_apply_gate_empty_is_noop() -> None:
    from ghostbrain.connectors._relevance import apply_relevance_gate

    kept, dropped = apply_relevance_gate([], lambda ev: (True, ""))
    assert kept == []
    assert dropped == 0


def test_build_gate_parses_llm_json(tmp_path, monkeypatch) -> None:
    from ghostbrain.connectors import _relevance

    prompt = tmp_path / "p.md"
    prompt.write_text("Decide: {{content}}", encoding="utf-8")

    fake_result = MagicMock()
    fake_result.as_json.return_value = {"relevant": True, "reason": "ok"}

    with patch.object(_relevance, "_llm_run", return_value=fake_result) as run:
        gate = _relevance.build_llm_gate(
            prompt_path=prompt,
            model="haiku",
            excerpt_fn=lambda ev: f"X{ev['id']}",
        )
        relevant, reason = gate({"id": "9"})

    assert relevant is True
    assert reason == "ok"
    # Prompt template had {{content}} substituted with the excerpt.
    sent_prompt = run.call_args.args[0]
    assert "X9" in sent_prompt
    assert "{{content}}" not in sent_prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_relevance_gate.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `connectors/_relevance.py`**

```python
"""Shared LLM relevance gate for noisy connectors (Outlook mail, Teams chat).

A gate is a callable ``(event) -> (relevant: bool, reason: str)``. The gate
itself wraps a single Haiku call with a JSON schema and a hard USD budget.
``apply_relevance_gate`` runs a gate over a list of events and is conservative
on error: an LLM failure keeps the event so real signal is never silently
swallowed (matching the Gmail connector's behaviour)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

log = logging.getLogger("ghostbrain.connectors.relevance")

Gate = Callable[[dict], "tuple[bool, str]"]

RELEVANCE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": ["relevant", "reason"],
    "properties": {
        "relevant": {"type": "boolean"},
        "reason": {"type": "string", "maxLength": 200},
    },
}

# ~$0.06 of cache-creation overhead per `claude -p` call means a lower cap
# silently busts every check; $0.15 gives haiku headroom for one JSON reply.
DEFAULT_GATE_BUDGET_USD = 0.15


def _llm_run(prompt: str, *, model: str, json_schema: dict, budget_usd: float):
    """Indirection seam so tests can patch the LLM without importing it."""
    from ghostbrain.llm import client as llm

    return llm.run(prompt, model=model, json_schema=json_schema, budget_usd=budget_usd)


def build_llm_gate(
    *,
    prompt_path: Path,
    model: str,
    excerpt_fn: Callable[[dict], str],
    budget_usd: float = DEFAULT_GATE_BUDGET_USD,
) -> Gate:
    """Build a gate from a prompt template file. The template must contain
    ``{{content}}``; ``excerpt_fn`` renders the per-event text inserted there."""
    if not prompt_path.exists():
        raise FileNotFoundError(
            f"missing relevance prompt {prompt_path}; re-run `ghostbrain-bootstrap`"
        )
    template = prompt_path.read_text(encoding="utf-8")

    def gate(event: dict) -> tuple[bool, str]:
        prompt = template.replace("{{content}}", excerpt_fn(event))
        result = _llm_run(
            prompt, model=model, json_schema=RELEVANCE_SCHEMA, budget_usd=budget_usd
        )
        payload = result.as_json()
        return bool(payload.get("relevant")), str(payload.get("reason") or "")

    return gate


def apply_relevance_gate(events: list[dict], gate: Gate) -> tuple[list[dict], int]:
    """Run ``gate`` over events. Returns ``(kept, dropped_count)``. On gate
    error the event is kept (conservative). Kept events get
    ``metadata.relevanceReason`` set."""
    if not events:
        return events, 0
    kept: list[dict] = []
    dropped = 0
    for ev in events:
        try:
            relevant, reason = gate(ev)
        except Exception as e:  # noqa: BLE001
            log.warning("relevance gate errored for %s: %s — keeping", ev.get("id"), e)
            kept.append(ev)
            continue
        if relevant:
            ev.setdefault("metadata", {})["relevanceReason"] = reason
            kept.append(ev)
        else:
            dropped += 1
            log.info("dropped by relevance gate id=%s reason=%s", ev.get("id"), reason)
    return kept, dropped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_relevance_gate.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/_relevance.py tests/test_relevance_gate.py
git commit -m "feat(connectors): shared LLM relevance gate helper"
```

---

## Task 6: Teams meetings connector

Built first of the three because its fetch logic is already proven in the prototype. No relevance gate.

**Files:**
- Create: `ghostbrain/connectors/microsoft/teams_meetings/__init__.py`
- Create: `ghostbrain/connectors/microsoft/teams_meetings/connector.py`
- Test: `tests/test_teams_meetings_connector.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_teams_meetings_connector.py`:

```python
"""Tests for the Teams meetings connector. GraphClient is mocked."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _conn(tmp_path: Path, client) -> "object":
    from ghostbrain.connectors.microsoft.teams_meetings.connector import (
        TeamsMeetingsConnector,
    )
    return TeamsMeetingsConnector(
        config={"calendar_lookback_days": 7, "body_cap_chars": 100},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        client=client,
    )


def test_normalize_transcript_shape(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.teams_meetings.connector import (
        _normalize_transcript,
    )
    event = _normalize_transcript(
        meeting={"id": "m1", "subject": "Standup",
                 "joinWebUrl": "https://teams/x",
                 "participants": {"organizer": {"upn": "a@b.com"}}},
        transcript={"id": "t1", "createdDateTime": "2026-06-04T09:00:00Z",
                    "endDateTime": "2026-06-04T09:30:00Z"},
        text="WEBVTT\n\nhello world",
        body_cap=100,
    )
    assert event["id"] == "microsoft:transcript:m1:t1"
    assert event["source"] == "teams_meetings"
    assert event["type"] == "meeting_transcript"
    assert event["title"] == "Standup"
    assert "hello world" in event["body"]
    assert event["metadata"]["meetingId"] == "m1"
    assert event["metadata"]["transcriptId"] == "t1"


def test_body_is_capped(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.teams_meetings.connector import (
        _normalize_transcript,
    )
    event = _normalize_transcript(
        meeting={"id": "m", "subject": "S"},
        transcript={"id": "t", "createdDateTime": "2026-06-04T09:00:00Z"},
        text="x" * 5000,
        body_cap=100,
    )
    assert len(event["body"]) == 100


def test_fetch_emits_only_transcripts_newer_than_since(tmp_path) -> None:
    client = MagicMock()
    # One calendar event with an online meeting.
    client.get_all.side_effect = [
        # /me/events
        [{"id": "e1", "isOnlineMeeting": True,
          "onlineMeeting": {"joinUrl": "https://teams/join1"}}],
    ]
    # resolve_meeting -> /me/onlineMeetings filter
    client.get.side_effect = [
        {"value": [{"id": "m1", "subject": "Sync", "joinWebUrl": "https://teams/join1"}]},
        # list transcripts
        {"value": [
            {"id": "old", "createdDateTime": "2026-06-01T09:00:00Z"},
            {"id": "new", "createdDateTime": "2026-06-04T09:00:00Z"},
        ]},
        # transcript content for "new" only
        # (get_transcript_text uses .get with $format -> returns object w/ text)
    ]
    conn = _conn(tmp_path, client)

    # Stub transcript text fetch so we don't need a 4th .get.
    conn._fetch_transcript_text = lambda mid, tid: "WEBVTT\n\nbody"

    since = datetime(2026, 6, 3, tzinfo=timezone.utc)
    events = conn.fetch(since)

    ids = [e["id"] for e in events]
    assert ids == ["microsoft:transcript:m1:new"]


def test_health_check_false_without_token(tmp_path, monkeypatch) -> None:
    # Patch the symbol the connector module bound at import time.
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.teams_meetings.connector.have_token",
        lambda cfg: False,
    )
    conn = _conn(tmp_path, MagicMock())
    assert conn.health_check() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_teams_meetings_connector.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `teams_meetings/connector.py`**

```python
"""Teams meeting transcripts connector.

Walks the calendar over a rolling window, resolves each online meeting,
lists its transcripts, and emits only transcripts created since last_run
(the dedup mechanism). Transcripts are pulled deliberately, so there is no
relevance gate. Carries over resolve/list/fetch logic from the
pull_transcript.py prototype."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors.microsoft.graph.auth import (
    MicrosoftAuthError,
    get_token,
    have_token,
)
from ghostbrain.connectors.microsoft.graph.client import GraphClient

log = logging.getLogger("ghostbrain.connectors.teams_meetings")

DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_BODY_CAP_CHARS = 200_000


class TeamsMeetingsConnector(Connector):
    name = "teams_meetings"
    version = "1.0"

    def __init__(self, config, queue_dir, state_dir, *, client=None) -> None:
        super().__init__(config, queue_dir, state_dir)
        self.lookback_days = int(config.get("calendar_lookback_days") or DEFAULT_LOOKBACK_DAYS)
        self.body_cap = int(config.get("body_cap_chars") or DEFAULT_BODY_CAP_CHARS)
        self._client = client  # injected in tests

    def health_check(self) -> bool:
        return have_token(self.config)

    def _graph(self) -> GraphClient:
        if self._client is not None:
            return self._client
        return GraphClient(get_token(self.config))

    def fetch(self, since: datetime) -> list[dict]:
        client = self._graph()
        window_start = datetime.now(timezone.utc) - timedelta(days=self.lookback_days)
        events: list[dict] = []
        for ev in self._list_calendar_online_meetings(client, window_start):
            join_url = (ev.get("onlineMeeting") or {}).get("joinUrl")
            if not join_url:
                continue
            try:
                meeting = self._resolve_meeting(client, join_url)
            except MicrosoftAuthError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("could not resolve meeting %s: %s", join_url, e)
                continue
            events.extend(self._transcripts_for(client, meeting, since))
        log.info("teams_meetings fetch: %d new transcript(s)", len(events))
        return events

    def normalize(self, raw: dict) -> dict:
        return raw  # fetch already produces normalized events

    # -- Graph calls ---------------------------------------------------------

    def _list_calendar_online_meetings(self, client, window_start) -> list[dict]:
        params = {
            "$filter": f"start/dateTime ge '{window_start.isoformat()}'",
            "$select": "id,subject,isOnlineMeeting,onlineMeeting",
            "$top": 50,
            "$orderby": "start/dateTime desc",
        }
        return client.get_all("/me/events", params, max_items=100)

    def _resolve_meeting(self, client, join_url: str) -> dict:
        params = {"$filter": f"JoinWebUrl eq '{join_url}'"}
        items = client.get("/me/onlineMeetings", params).get("value") or []
        if not items:
            raise ValueError("no onlineMeeting matched join url")
        return items[0]

    def _transcripts_for(self, client, meeting: dict, since: datetime) -> list[dict]:
        meeting_id = meeting["id"]
        listed = client.get(f"/me/onlineMeetings/{meeting_id}/transcripts").get("value") or []
        out: list[dict] = []
        for t in listed:
            created = _parse_dt(t.get("createdDateTime"))
            if created is None or created <= since:
                continue
            text = self._fetch_transcript_text(meeting_id, t["id"])
            out.append(_normalize_transcript(meeting, t, text, self.body_cap))
        return out

    def _fetch_transcript_text(self, meeting_id: str, transcript_id: str) -> str:
        # Transcript content is VTT text, not JSON, so bypass GraphClient.get
        # (which parses JSON) and fetch raw text.
        client = self._graph()
        url = f"/me/onlineMeetings/{meeting_id}/transcripts/{transcript_id}/content"
        return _raw_text(client, url)


# -- pure helpers ------------------------------------------------------------


def _raw_text(client: GraphClient, path: str) -> str:
    """Fetch VTT transcript content as text (not JSON)."""
    import requests

    from ghostbrain.connectors.microsoft.graph.auth import GRAPH as _G

    url = path if path.startswith("http") else f"{_G}{path}"
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {client._token}"},
        params={"$format": "text/vtt"},
        timeout=30,
    )
    if r.status_code == 401:
        raise MicrosoftAuthError("Graph 401 fetching transcript; re-run auth.")
    r.raise_for_status()
    return r.text


def _parse_dt(value):
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _normalize_transcript(meeting: dict, transcript: dict, text: str, body_cap: int) -> dict:
    meeting_id = meeting.get("id") or ""
    transcript_id = transcript.get("id") or ""
    subject = meeting.get("subject") or "meeting"
    ts = transcript.get("endDateTime") or transcript.get("createdDateTime") or ""
    organizer = ((meeting.get("participants") or {}).get("organizer") or {})
    return {
        "id": f"microsoft:transcript:{meeting_id}:{transcript_id}",
        "source": "teams_meetings",
        "type": "meeting_transcript",
        "timestamp": _parse_dt(ts).isoformat() if _parse_dt(ts) else ts,
        "actorId": f"microsoft:{organizer.get('upn')}" if organizer.get("upn") else "",
        "title": subject,
        "body": (text or "")[:body_cap],
        "sourceUrl": meeting.get("joinWebUrl") or "",
        "metadata": {
            "meetingId": meeting_id,
            "transcriptId": transcript_id,
            "joinWebUrl": meeting.get("joinWebUrl") or "",
            "organizer": organizer.get("upn") or "",
        },
    }
```

`ghostbrain/connectors/microsoft/teams_meetings/__init__.py`:

```python
"""Teams meeting transcripts connector."""
from ghostbrain.connectors.microsoft.teams_meetings.connector import (
    TeamsMeetingsConnector,
)

__all__ = ["TeamsMeetingsConnector"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_teams_meetings_connector.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/microsoft/teams_meetings/ tests/test_teams_meetings_connector.py
git commit -m "feat(microsoft): teams meeting transcripts connector"
```

---

## Task 7: Outlook mail connector

**Files:**
- Create: `ghostbrain/connectors/microsoft/outlook_mail/__init__.py`
- Create: `ghostbrain/connectors/microsoft/outlook_mail/connector.py`
- Test: `tests/test_outlook_mail_connector.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_outlook_mail_connector.py`:

```python
"""Tests for the Outlook mail connector. GraphClient + gate are injected."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock


def _conn(tmp_path, client, *, gate=None, denylist=None):
    from ghostbrain.connectors.microsoft.outlook_mail.connector import (
        OutlookMailConnector,
    )
    return OutlookMailConnector(
        config={
            "unread_lookback_hours": 24,
            "denylist_domains": denylist or [],
            "relevance_gate": gate is not None,
            "max_messages_per_run": 50,
        },
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        client=client,
        relevance_gate=gate,
    )


def _msg(mid, sender, subject="Hi", read=False):
    return {
        "id": mid,
        "subject": subject,
        "isRead": read,
        "receivedDateTime": "2026-06-04T09:00:00Z",
        "bodyPreview": "preview text",
        "from": {"emailAddress": {"address": sender, "name": "Someone"}},
        "toRecipients": [{"emailAddress": {"address": "me@example.com"}}],
        "webLink": "https://outlook/x",
    }


def test_normalize_message_shape(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.outlook_mail.connector import _normalize_message
    ev = _normalize_message(_msg("a1", "boss@example.com"), body_cap=4000)
    assert ev["id"] == "microsoft:mail:a1"
    assert ev["source"] == "outlook_mail"
    assert ev["type"] == "email"
    assert ev["metadata"]["from_domain"] == "example.com"
    assert ev["actorId"] == "microsoft:boss@example.com"


def test_fetch_applies_denylist(tmp_path) -> None:
    client = MagicMock()
    client.get_all.return_value = [
        _msg("a", "ok@example.com"),
        _msg("b", "spam@noisy.com"),
    ]
    conn = _conn(tmp_path, client, denylist=["noisy.com"])
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["metadata"]["from_address"] for e in events] == ["ok@example.com"]


def test_fetch_applies_relevance_gate(tmp_path) -> None:
    client = MagicMock()
    client.get_all.return_value = [
        _msg("a", "boss@example.com", subject="Project update"),
        _msg("b", "newsletter@example.com", subject="Weekly digest"),
    ]

    def gate(ev):
        return ("digest" not in ev["title"].lower(), "r")

    conn = _conn(tmp_path, client, gate=gate)
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["id"] for e in events] == ["microsoft:mail:a"]


def test_health_check_false_without_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.outlook_mail.connector.have_token",
        lambda cfg: False,
    )
    conn = _conn(tmp_path, MagicMock())
    assert conn.health_check() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_outlook_mail_connector.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `outlook_mail/connector.py`**

```python
"""Outlook mail connector. Polls /me/messages for unread mail within a
lookback window (and/or monitored folders), applies a denylist + the shared
LLM relevance gate, and emits one event per message."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors._relevance import apply_relevance_gate, build_llm_gate
from ghostbrain.connectors.microsoft.graph.auth import get_token, have_token
from ghostbrain.connectors.microsoft.graph.client import GraphClient

log = logging.getLogger("ghostbrain.connectors.outlook_mail")

DEFAULT_LOOKBACK_HOURS = 24
DEFAULT_MAX_PER_RUN = 50
DEFAULT_BODY_CAP_CHARS = 4000
DEFAULT_RELEVANCE_MODEL = "haiku"


class OutlookMailConnector(Connector):
    name = "outlook_mail"
    version = "1.0"

    def __init__(self, config, queue_dir, state_dir, *, client=None, relevance_gate=None):
        super().__init__(config, queue_dir, state_dir)
        self.lookback_hours = int(config.get("unread_lookback_hours") or DEFAULT_LOOKBACK_HOURS)
        self.max_per_run = int(config.get("max_messages_per_run") or DEFAULT_MAX_PER_RUN)
        self.denylist = [d.lower() for d in (config.get("denylist_domains") or [])]
        self.relevance_enabled = bool(config.get("relevance_gate", True))
        self.relevance_model = str(config.get("relevance_model") or DEFAULT_RELEVANCE_MODEL)
        self._client = client
        self._gate_override = relevance_gate

    def health_check(self) -> bool:
        return have_token(self.config)

    def _graph(self) -> GraphClient:
        return self._client if self._client is not None else GraphClient(get_token(self.config))

    def fetch(self, since: datetime) -> list[dict]:
        client = self._graph()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        params = {
            "$filter": f"isRead eq false and receivedDateTime ge {cutoff.isoformat()}",
            "$select": "id,subject,isRead,receivedDateTime,bodyPreview,from,toRecipients,webLink",
            "$top": self.max_per_run,
            "$orderby": "receivedDateTime desc",
        }
        msgs = client.get_all("/me/messages", params, max_items=self.max_per_run)
        events = [_normalize_message(m, DEFAULT_BODY_CAP_CHARS) for m in msgs]

        raw = len(events)
        events = [e for e in events if not _is_denied(e, self.denylist)]
        denied = raw - len(events)

        if self.relevance_enabled:
            gate = self._gate_override or self._default_gate()
            events, dropped = apply_relevance_gate(events, gate)
        else:
            dropped = 0
        log.info("outlook_mail fetch: %d kept (%d denied, %d gated, %d initial)",
                 len(events), denied, dropped, raw)
        return events

    def normalize(self, raw: dict) -> dict:
        return raw

    def _default_gate(self):
        from ghostbrain.paths import vault_path

        return build_llm_gate(
            prompt_path=vault_path() / "90-meta" / "prompts" / "outlook-mail-relevance.md",
            model=self.relevance_model,
            excerpt_fn=_mail_excerpt,
        )


def _normalize_message(m: dict, body_cap: int) -> dict:
    addr_obj = (m.get("from") or {}).get("emailAddress") or {}
    from_addr = (addr_obj.get("address") or "").lower()
    from_domain = from_addr.split("@", 1)[1] if "@" in from_addr else ""
    to_addrs = [
        (r.get("emailAddress") or {}).get("address", "")
        for r in (m.get("toRecipients") or [])
    ]
    return {
        "id": f"microsoft:mail:{m.get('id') or ''}",
        "source": "outlook_mail",
        "type": "email",
        "subtype": "read" if m.get("isRead") else "unread",
        "timestamp": m.get("receivedDateTime") or "",
        "actorId": f"microsoft:{from_addr}" if from_addr else "",
        "title": m.get("subject") or "(no subject)",
        "body": (m.get("bodyPreview") or "")[:body_cap],
        "sourceUrl": m.get("webLink") or "",
        "metadata": {
            "from": addr_obj.get("name") or from_addr,
            "from_address": from_addr,
            "from_domain": from_domain,
            "to": to_addrs,
            "is_unread": not m.get("isRead"),
        },
    }


def _is_denied(event: dict, denylist: list[str]) -> bool:
    if not denylist:
        return False
    domain = ((event.get("metadata") or {}).get("from_domain") or "").lower()
    if not domain:
        return False
    for pat in denylist:
        pat = pat.strip().lower()
        if not pat:
            continue
        if pat.startswith("*."):
            tail = pat[2:]
            if domain == tail or domain.endswith("." + tail):
                return True
        elif domain == pat:
            return True
    return False


def _mail_excerpt(event: dict) -> str:
    md = event.get("metadata") or {}
    return "\n".join([
        f"From: {md.get('from_address') or ''}",
        f"Subject: {event.get('title') or ''}",
        "",
        (event.get("body") or "")[:1000],
    ])
```

`ghostbrain/connectors/microsoft/outlook_mail/__init__.py`:

```python
"""Outlook mail connector."""
from ghostbrain.connectors.microsoft.outlook_mail.connector import OutlookMailConnector

__all__ = ["OutlookMailConnector"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_outlook_mail_connector.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/microsoft/outlook_mail/ tests/test_outlook_mail_connector.py
git commit -m "feat(microsoft): outlook mail connector with relevance gate"
```

---

## Task 8: Teams chat connector

**Files:**
- Create: `ghostbrain/connectors/microsoft/teams_chat/__init__.py`
- Create: `ghostbrain/connectors/microsoft/teams_chat/connector.py`
- Test: `tests/test_teams_chat_connector.py`

- [ ] **Step 1: Write the failing tests**

`tests/test_teams_chat_connector.py`:

```python
"""Tests for the Teams chat connector. GraphClient + gate are injected."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock


def _conn(tmp_path, client, *, gate=None):
    from ghostbrain.connectors.microsoft.teams_chat.connector import TeamsChatConnector
    return TeamsChatConnector(
        config={"max_messages_per_run": 100, "relevance_gate": gate is not None},
        queue_dir=tmp_path / "q",
        state_dir=tmp_path / "s",
        client=client,
        relevance_gate=gate,
    )


def _chat_msg(mid, body, created="2026-06-04T09:00:00Z", mtype="message"):
    return {
        "id": mid,
        "messageType": mtype,
        "createdDateTime": created,
        "body": {"content": body, "contentType": "text"},
        "from": {"user": {"id": "u1", "displayName": "Alice"}},
    }


def test_normalize_chat_message_shape(tmp_path) -> None:
    from ghostbrain.connectors.microsoft.teams_chat.connector import _normalize_message
    ev = _normalize_message(
        chat={"id": "c1", "chatType": "oneOnOne", "topic": None,
              "webUrl": "https://teams/c1"},
        msg=_chat_msg("m1", "hello there"),
    )
    assert ev["id"] == "microsoft:chat:c1:m1"
    assert ev["source"] == "teams_chat"
    assert ev["type"] == "chat_message"
    assert ev["body"] == "hello there"
    assert ev["metadata"]["chatType"] == "oneOnOne"


def test_fetch_drops_system_messages(tmp_path) -> None:
    client = MagicMock()
    client.get_all.side_effect = [
        # /me/chats
        [{"id": "c1", "chatType": "group", "topic": "Team", "webUrl": "u",
          "lastUpdatedDateTime": "2026-06-04T10:00:00Z"}],
        # /me/chats/c1/messages
        [
            _chat_msg("m1", "real message"),
            _chat_msg("sys", "joined", mtype="systemEventMessage"),
        ],
    ]
    conn = _conn(tmp_path, client)
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["id"] for e in events] == ["microsoft:chat:c1:m1"]


def test_fetch_filters_messages_by_since(tmp_path) -> None:
    client = MagicMock()
    client.get_all.side_effect = [
        [{"id": "c1", "chatType": "oneOnOne", "webUrl": "u",
          "lastUpdatedDateTime": "2026-06-04T10:00:00Z"}],
        [
            _chat_msg("old", "old", created="2026-06-01T09:00:00Z"),
            _chat_msg("new", "new", created="2026-06-04T09:00:00Z"),
        ],
    ]
    conn = _conn(tmp_path, client)
    events = conn.fetch(datetime(2026, 6, 3, tzinfo=timezone.utc))
    assert [e["id"] for e in events] == ["microsoft:chat:c1:new"]


def test_health_check_false_without_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.teams_chat.connector.have_token",
        lambda cfg: False,
    )
    conn = _conn(tmp_path, MagicMock())
    assert conn.health_check() is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_teams_chat_connector.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `teams_chat/connector.py`**

```python
"""Teams chat connector. Lists /me/chats, pulls messages created since
last_run from active chats (capped, system messages dropped), applies the
shared LLM relevance gate, and emits one event per message."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from ghostbrain.connectors._base import Connector
from ghostbrain.connectors._relevance import apply_relevance_gate, build_llm_gate
from ghostbrain.connectors.microsoft.graph.auth import get_token, have_token
from ghostbrain.connectors.microsoft.graph.client import GraphClient

log = logging.getLogger("ghostbrain.connectors.teams_chat")

DEFAULT_MAX_PER_RUN = 100
DEFAULT_RELEVANCE_MODEL = "haiku"
_SYSTEM_TYPES = {"systemEventMessage"}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class TeamsChatConnector(Connector):
    name = "teams_chat"
    version = "1.0"

    def __init__(self, config, queue_dir, state_dir, *, client=None, relevance_gate=None):
        super().__init__(config, queue_dir, state_dir)
        self.max_per_run = int(config.get("max_messages_per_run") or DEFAULT_MAX_PER_RUN)
        self.relevance_enabled = bool(config.get("relevance_gate", True))
        self.relevance_model = str(config.get("relevance_model") or DEFAULT_RELEVANCE_MODEL)
        self._client = client
        self._gate_override = relevance_gate

    def health_check(self) -> bool:
        return have_token(self.config)

    def _graph(self) -> GraphClient:
        return self._client if self._client is not None else GraphClient(get_token(self.config))

    def fetch(self, since: datetime) -> list[dict]:
        client = self._graph()
        chats = client.get_all("/me/chats", {"$top": 50}, max_items=50)
        events: list[dict] = []
        for chat in chats:
            if len(events) >= self.max_per_run:
                break
            last = _parse_dt(chat.get("lastUpdatedDateTime"))
            if last is not None and last <= since:
                continue
            try:
                events.extend(self._messages_for(client, chat, since))
            except Exception as e:  # noqa: BLE001
                log.warning("teams_chat: chat %s failed: %s", chat.get("id"), e)

        raw = len(events)
        if self.relevance_enabled and events:
            gate = self._gate_override or self._default_gate()
            events, dropped = apply_relevance_gate(events, gate)
        else:
            dropped = 0
        log.info("teams_chat fetch: %d kept (%d gated, %d initial)", len(events), dropped, raw)
        return events

    def normalize(self, raw: dict) -> dict:
        return raw

    def _messages_for(self, client, chat: dict, since: datetime) -> list[dict]:
        cid = chat["id"]
        msgs = client.get_all(f"/me/chats/{cid}/messages", {"$top": 50}, max_items=self.max_per_run)
        out = []
        for m in msgs:
            if m.get("messageType") in _SYSTEM_TYPES:
                continue
            created = _parse_dt(m.get("createdDateTime"))
            if created is None or created <= since:
                continue
            ev = _normalize_message(chat, m)
            if ev["body"]:
                out.append(ev)
        return out

    def _default_gate(self):
        from ghostbrain.paths import vault_path

        return build_llm_gate(
            prompt_path=vault_path() / "90-meta" / "prompts" / "teams-chat-relevance.md",
            model=self.relevance_model,
            excerpt_fn=_chat_excerpt,
        )


def _parse_dt(value):
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    v = re.sub(r"(\.\d{6})\d+", r"\1", v)
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        return None


def _normalize_message(chat: dict, msg: dict) -> dict:
    cid = chat.get("id") or ""
    mid = msg.get("id") or ""
    sender = ((msg.get("from") or {}).get("user") or {})
    body_obj = msg.get("body") or {}
    content = body_obj.get("content") or ""
    if (body_obj.get("contentType") or "").lower() == "html":
        content = _HTML_TAG_RE.sub("", content).strip()
    topic = chat.get("topic") or sender.get("displayName") or "chat"
    return {
        "id": f"microsoft:chat:{cid}:{mid}",
        "source": "teams_chat",
        "type": "chat_message",
        "timestamp": msg.get("createdDateTime") or "",
        "actorId": f"microsoft:{sender.get('id')}" if sender.get("id") else "",
        "title": topic,
        "body": content,
        "sourceUrl": chat.get("webUrl") or "",
        "metadata": {
            "chatId": cid,
            "chatType": chat.get("chatType") or "",
            "sender": sender.get("displayName") or "",
        },
    }


def _chat_excerpt(event: dict) -> str:
    md = event.get("metadata") or {}
    return "\n".join([
        f"Chat: {event.get('title') or ''} ({md.get('chatType') or ''})",
        f"From: {md.get('sender') or ''}",
        "",
        (event.get("body") or "")[:1000],
    ])
```

`ghostbrain/connectors/microsoft/teams_chat/__init__.py`:

```python
"""Teams chat connector."""
from ghostbrain.connectors.microsoft.teams_chat.connector import TeamsChatConnector

__all__ = ["TeamsChatConnector"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_teams_chat_connector.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/microsoft/teams_chat/ tests/test_teams_chat_connector.py
git commit -m "feat(microsoft): teams chat connector with relevance gate"
```

---

## Task 9: Runners + CLI entry points for all three connectors

**Files:**
- Create: `ghostbrain/connectors/microsoft/{outlook_mail,teams_chat,teams_meetings}/runner.py`
- Create: `ghostbrain/connectors/microsoft/{outlook_mail,teams_chat,teams_meetings}/__main__.py`

These follow `gmail/runner.py` and `gmail/__main__.py` exactly. Each runner returns `None` (skip) when its routing sub-block is absent.

- [ ] **Step 1: `teams_meetings/runner.py`**

```python
"""In-process runner for the Teams meetings connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.microsoft.teams_meetings import TeamsMeetingsConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path):
    ms = routing.get("microsoft") or {}
    cfg = ms.get("teams_meetings")
    if cfg is None:
        return None
    cfg = {**cfg, "client_id": ms.get("client_id"), "tenant_id": ms.get("tenant_id")}
    return TeamsMeetingsConnector(config=cfg, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("teams_meetings", build=_build)
```

- [ ] **Step 2: `outlook_mail/runner.py`**

```python
"""In-process runner for the Outlook mail connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.microsoft.outlook_mail import OutlookMailConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path):
    ms = routing.get("microsoft") or {}
    cfg = ms.get("outlook_mail")
    if cfg is None:
        return None
    cfg = {**cfg, "client_id": ms.get("client_id"), "tenant_id": ms.get("tenant_id")}
    return OutlookMailConnector(config=cfg, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("outlook_mail", build=_build)
```

- [ ] **Step 3: `teams_chat/runner.py`**

```python
"""In-process runner for the Teams chat connector."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.connectors._runner import RunResult, run_connector
from ghostbrain.connectors.microsoft.teams_chat import TeamsChatConnector


def _build(routing: dict, queue_dir: Path, state_dir: Path):
    ms = routing.get("microsoft") or {}
    cfg = ms.get("teams_chat")
    if cfg is None:
        return None
    cfg = {**cfg, "client_id": ms.get("client_id"), "tenant_id": ms.get("tenant_id")}
    return TeamsChatConnector(config=cfg, queue_dir=queue_dir, state_dir=state_dir)


def run() -> RunResult:
    return run_connector("teams_chat", build=_build)
```

- [ ] **Step 4: Three `__main__.py` files**

`ghostbrain/connectors/microsoft/teams_meetings/__main__.py`:

```python
"""CLI: python -m ghostbrain.connectors.microsoft.teams_meetings
or ghostbrain-teams-meetings-fetch."""
from __future__ import annotations

import logging

from ghostbrain.connectors.microsoft.teams_meetings.runner import run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run()
    if result.skipped_reason:
        print(f"teams_meetings: skipped ({result.skipped_reason})")
    elif result.ok:
        print(f"teams_meetings: queued {result.queued} event(s)")
    else:
        print(f"teams_meetings: FAILED — {result.error}")


if __name__ == "__main__":
    main()
```

`ghostbrain/connectors/microsoft/outlook_mail/__main__.py` — identical but replace every `teams_meetings` with `outlook_mail`:

```python
"""CLI: python -m ghostbrain.connectors.microsoft.outlook_mail
or ghostbrain-outlook-mail-fetch."""
from __future__ import annotations

import logging

from ghostbrain.connectors.microsoft.outlook_mail.runner import run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run()
    if result.skipped_reason:
        print(f"outlook_mail: skipped ({result.skipped_reason})")
    elif result.ok:
        print(f"outlook_mail: queued {result.queued} event(s)")
    else:
        print(f"outlook_mail: FAILED — {result.error}")


if __name__ == "__main__":
    main()
```

`ghostbrain/connectors/microsoft/teams_chat/__main__.py` — identical but replace every `teams_meetings` with `teams_chat`:

```python
"""CLI: python -m ghostbrain.connectors.microsoft.teams_chat
or ghostbrain-teams-chat-fetch."""
from __future__ import annotations

import logging

from ghostbrain.connectors.microsoft.teams_chat.runner import run


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    result = run()
    if result.skipped_reason:
        print(f"teams_chat: skipped ({result.skipped_reason})")
    elif result.ok:
        print(f"teams_chat: queued {result.queued} event(s)")
    else:
        print(f"teams_chat: FAILED — {result.error}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Verify runners skip cleanly with no config**

Run:
```bash
.venv/bin/python -c "
from ghostbrain.connectors.microsoft.outlook_mail.runner import _build
from ghostbrain.connectors.microsoft.teams_chat.runner import _build as cb
from ghostbrain.connectors.microsoft.teams_meetings.runner import _build as mb
from pathlib import Path
assert _build({}, Path('/tmp'), Path('/tmp')) is None
assert cb({}, Path('/tmp'), Path('/tmp')) is None
assert mb({}, Path('/tmp'), Path('/tmp')) is None
print('ok')
"
```
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/connectors/microsoft/*/runner.py ghostbrain/connectors/microsoft/*/__main__.py
git commit -m "feat(microsoft): runners and CLI entry points for all three connectors"
```

---

## Task 10: Wire scheduler, console scripts, and bootstrap config

**Files:**
- Modify: `ghostbrain/scheduler_jobs.py`
- Modify: `pyproject.toml`
- Modify: `ghostbrain/bootstrap.py`

- [ ] **Step 1: Register the three jobs in the scheduler**

In `ghostbrain/scheduler_jobs.py`, add imports near the other connector runner imports (after the `slack_runner` import, line ~25):

```python
from ghostbrain.connectors.microsoft.outlook_mail import runner as outlook_mail_runner
from ghostbrain.connectors.microsoft.teams_chat import runner as teams_chat_runner
from ghostbrain.connectors.microsoft.teams_meetings import runner as teams_meetings_runner
```

In `register_connectors`, after the `joplin` line, add:

```python
    scheduler.add_job("outlook_mail", Interval(seconds=3600), outlook_mail_runner.run, "every 1h")
    scheduler.add_job("teams_chat", Interval(seconds=3600), teams_chat_runner.run, "every 1h")
    scheduler.add_job("teams_meetings", Interval(seconds=7200), teams_meetings_runner.run, "every 2h")
```

- [ ] **Step 2: Add console scripts + verify deps in `pyproject.toml`**

In the `[project.scripts]` table (after `ghostbrain-joplin-fetch`):

```toml
ghostbrain-microsoft-auth = "ghostbrain.connectors.microsoft.graph.auth_cli:main"
ghostbrain-outlook-mail-fetch = "ghostbrain.connectors.microsoft.outlook_mail.__main__:main"
ghostbrain-teams-chat-fetch = "ghostbrain.connectors.microsoft.teams_chat.__main__:main"
ghostbrain-teams-meetings-fetch = "ghostbrain.connectors.microsoft.teams_meetings.__main__:main"
```

- [ ] **Step 3: Add the two relevance prompts in `bootstrap.py`**

Near `_GMAIL_RELEVANCE_PROMPT` (line ~173), add two constants:

```python
_OUTLOOK_MAIL_RELEVANCE_PROMPT = """\
<!-- Outlook mail relevance gate. Used by ghostbrain.connectors.microsoft.outlook_mail
to decide whether a work email should be ingested. Rejected mail is dropped silently. -->

RESPOND WITH JSON ONLY. NO PROSE. NO MARKDOWN FENCES. NO PREAMBLE.
Your entire response must be a single JSON object exactly matching:
`{"relevant": true|false, "reason": "<one short sentence>"}`

You are gating which work emails from the work Microsoft 365 tenant enter a
software engineer's personal knowledge system. The user works on their employer's projects
(their work areas).

Mark `relevant: true` ONLY when the email is plausibly worth surfacing in a
daily digest of work follow-ups: direct questions, decisions, action items,
incident/PR/ticket discussion, meeting follow-ups, anything you'd act on.

NOT relevant (set `relevant: false`):
- Automated notifications (build/deploy/monitoring/calendar reminders).
- Mass announcements, all-staff newsletters, HR/marketing blasts.
- Routine "FYI" cc's with no action.
- Anything you'd archive without reading.

Be conservative on dropping but decisive on noise: when in real doubt, prefer
`relevant: true` so signal is never silently swallowed.

`reason` is one short sentence (<= 120 chars) the user can read in the digest.

Email to judge:
{{content}}
"""

_TEAMS_CHAT_RELEVANCE_PROMPT = """\
<!-- Teams chat relevance gate. Used by ghostbrain.connectors.microsoft.teams_chat
to decide whether a chat message should be ingested. Rejected messages are dropped. -->

RESPOND WITH JSON ONLY. NO PROSE. NO MARKDOWN FENCES. NO PREAMBLE.
Your entire response must be a single JSON object exactly matching:
`{"relevant": true|false, "reason": "<one short sentence>"}`

You are gating which Teams chat messages from the work Microsoft 365 tenant
enter a software engineer's personal knowledge system.

Mark `relevant: true` ONLY when the message carries durable signal worth a daily
digest: a decision, a request/action item directed at the user, a question
needing follow-up, or a substantive technical/work discussion.

NOT relevant (set `relevant: false`):
- Pleasantries, reactions, "thanks", "ok", "lol", emoji-only.
- Logistics already captured elsewhere (calendar invites, meeting join links).
- Idle chatter with no follow-up.

Be conservative on dropping but decisive on noise: when in real doubt, prefer
`relevant: true`.

`reason` is one short sentence (<= 120 chars).

Message to judge:
{{content}}
"""
```

Then register both in the prompts dict (near the `gmail-relevance.md` entry, line ~739):

```python
    "90-meta/prompts/outlook-mail-relevance.md": _OUTLOOK_MAIL_RELEVANCE_PROMPT,
    "90-meta/prompts/teams-chat-relevance.md": _TEAMS_CHAT_RELEVANCE_PROMPT,
```

- [ ] **Step 4: Add the `microsoft:` routing.yaml block in `bootstrap.py`**

Find the routing.yaml content in the bootstrap files dict (the entry whose value contains `excluded_titles:` near line ~730 — this is the `90-meta/routing.yaml` seed). Append a `microsoft:` block to that YAML string, before its closing `"""`:

```yaml
microsoft:
  # client_id / tenant_id default to the registered Entra app; override here if needed.
  outlook_mail:
    unread_lookback_hours: 24
    denylist_domains: []
    relevance_gate: true
    relevance_model: haiku
    max_messages_per_run: 50
  teams_chat:
    max_messages_per_run: 100
    relevance_gate: true
    relevance_model: haiku
  teams_meetings:
    calendar_lookback_days: 7
    body_cap_chars: 200000
```

(Match the existing indentation of that YAML literal exactly. Confirm the seed key with `grep -n "excluded_titles" ghostbrain/bootstrap.py` and read the surrounding string first.)

- [ ] **Step 5: Verify scheduler imports and registration**

Run:
```bash
.venv/bin/python -c "
from ghostbrain.scheduler_jobs import register_connectors
from ghostbrain.scheduler import Scheduler
import inspect
src = inspect.getsource(register_connectors)
for n in ('outlook_mail', 'teams_chat', 'teams_meetings'):
    assert n in src, n
print('ok')
"
```
Expected: `ok`

- [ ] **Step 6: Reinstall to pick up new console scripts**

Run: `.venv/bin/python -m pip install -e . >/dev/null && which ghostbrain-microsoft-auth || .venv/bin/ghostbrain-microsoft-auth --help 2>&1 | head -1`
Expected: the entry point resolves (help or device-flow prompt; an auth error is fine — it proves wiring).

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/scheduler_jobs.py pyproject.toml ghostbrain/bootstrap.py
git commit -m "feat(microsoft): wire scheduler jobs, console scripts, bootstrap prompts + routing"
```

---

## Task 11: Full test suite + manual smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the whole connector test suite**

Run: `.venv/bin/python -m pytest tests/test_microsoft_auth.py tests/test_microsoft_graph_client.py tests/test_relevance_gate.py tests/test_outlook_mail_connector.py tests/test_teams_chat_connector.py tests/test_teams_meetings_connector.py -v`
Expected: all PASS.

- [ ] **Step 2: Run the full repo test suite to catch regressions**

Run: `.venv/bin/python -m pytest -q`
Expected: no new failures versus the pre-change baseline. (If pre-existing failures exist, confirm they are unrelated to `microsoft`/`_relevance`.)

- [ ] **Step 3: Manual auth smoke (requires Entra prerequisite done — see below)**

Run: `.venv/bin/ghostbrain-microsoft-auth`
Expected: prints a device-code URL + code; after completing sign-in in the browser, prints `OK — signed in as <you>; token cached.` and writes `~/.ghostbrain/state/microsoft/token_cache.bin`.

- [ ] **Step 4: Manual fetch smoke (dry, low blast radius)**

Run each and confirm a sane `queued N` / `skipped` line and no traceback:
```bash
.venv/bin/ghostbrain-teams-meetings-fetch
.venv/bin/ghostbrain-outlook-mail-fetch
.venv/bin/ghostbrain-teams-chat-fetch
```
Expected: each prints `queued N event(s)` (N may be 0) or `skipped (not configured)` if you haven't added the `microsoft:` block to your live `vault/90-meta/routing.yaml` yet. Inspect a queued file under the queue's `pending/` to confirm the event shape.

- [ ] **Step 5: Final commit (if any smoke-driven fixes were needed)**

```bash
git add -A
git commit -m "test(microsoft): verify connector suite and manual smoke"
```

---

## ⚠️ Prerequisite before Task 11 Steps 3–4 (you / tenant admin, outside the code)

The prototype's Entra app (the prototype app) only has `OnlineMeetings.Read` + `OnlineMeetingTranscript.Read.All`. Before mail/chat fetch works, the app registration needs, as **delegated** permissions:
- `Mail.Read`
- `Chat.Read`
- `Calendars.Read`

…plus **"Allow public client flows"** enabled and **admin consent** re-granted on the tenant. Until then, `ghostbrain-microsoft-auth` may sign in but mail/chat/calendar Graph calls will 403. The unit tests (Steps 1–2) do **not** depend on this — they mock Graph entirely.

---

## Notes for the executor

- **TDD throughout:** every connector test is written and seen failing before the implementation.
- **DRY:** the relevance gate lives once in `_relevance.py`; the Graph HTTP + paging lives once in `client.py`; auth lives once in `graph/auth.py`. The Gmail connector is intentionally left untouched.
- **Injection seams:** every connector takes `client=` and (for mail/chat) `relevance_gate=` kwargs so tests never touch the network or the LLM. Follow this — do not add real Graph/LLM calls into tests.
- **Dedup contract:** each `fetch` filters by its own timestamp vs the `since` passed by the base `run()` loop (`receivedDateTime` / message `createdDateTime` / transcript `createdDateTime`). Do not add separate seen-id state files.
